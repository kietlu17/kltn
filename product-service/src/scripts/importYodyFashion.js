/* Import the attributed YODY fashion snapshot into the demo catalog. */
const fs = require('node:fs');
const path = require('node:path');
const mongoose = require('mongoose');
const { connectMongo } = require('../config/db');
const Product = require('../models/Product');
const Category = require('../models/Category');
const { initProducer, closeProducer, publishProductCreated } = require('../kafka/producer');

const SHOP_ID = process.env.YODY_IMPORT_SHOP_ID || '69f1b1cb00f071907a7e0fd4';
const INPUT = path.resolve(process.env.YODY_IMPORT_INPUT || 'output/catalog/yody-fashion.jsonl');
const APPLY = process.argv.includes('--apply');
const RESYNC_STOCK = process.argv.includes('--resync-stock');
const LIMIT = Number(process.env.YODY_IMPORT_LIMIT || 1000);
const DEFAULT_STOCK = 100;

function escapeHtml(value) {
  return String(value || '').replaceAll('&', '&amp;').replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

function readRecords() {
  const records = fs.readFileSync(INPUT, 'utf8').split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
  const ids = new Set();
  for (const record of records) {
    if (!/^\d+$/.test(String(record.sourceId)) || ids.has(String(record.sourceId))) {
      throw new Error(`Invalid or duplicate YODY source ID: ${record.sourceId}`);
    }
    if (!record.sourceUrl.startsWith('https://yody.vn/product/') || !record.name ||
        !record.categoryName || !record.description || !record.images?.length ||
        !record.variants?.length || !(record.price > 0)) {
      throw new Error(`Incomplete source record: ${record.sourceId}`);
    }
    ids.add(String(record.sourceId));
  }
  if (records.length < LIMIT) throw new Error(`Snapshot has ${records.length}/${LIMIT} products`);
  return records.slice(0, LIMIT);
}

function fillDefaultStock(variants) {
  if (!variants.length || variants.some((variant) => Number(variant.quantity || 0) > 0)) return false;
  const perVariant = Math.floor(DEFAULT_STOCK / variants.length);
  const remainder = DEFAULT_STOCK % variants.length;
  variants.forEach((variant, index) => {
    variant.quantity = perVariant + (index < remainder ? 1 : 0);
  });
  return true;
}

function buildProduct(record, categoryId) {
  const detail = [
    `Danh mục: ${record.categoryName}.`,
    `Nguồn: ${record.sourceUrl}`,
    'Giá tham khảo từ nguồn; tồn kho mặc định 100 là dữ liệu nội bộ.'
  ].join('\n');
  const variants = record.variants.map((variant) => ({
    name: variant.name,
    sku: variant.sku,
    imageUrl: variant.imageUrl,
    originalPrice: variant.originalPrice,
    price: variant.price,
    quantity: variant.quantity
  }));
  const defaultedStock = fillDefaultStock(variants);
  return {
    name: record.name,
    description: record.sourceDetail || record.description,
    detail,
    sourceProvider: 'yody',
    sourceProductId: String(record.sourceId),
    sourceUrl: record.sourceUrl,
    images: record.images,
    originalPrice: record.originalPrice,
    price: record.price,
    quantity: variants.reduce((sum, variant) => sum + variant.quantity, 0),
    sold: 0,
    variants,
    categoryId: String(categoryId),
    shopId: SHOP_ID,
    moderationStatus: 'approved',
    moderatedBy: 'yody-fashion-import',
    moderatedAt: new Date(),
    moderationNote: defaultedStock
      ? 'Public YODY catalog reference; default demo stock 100 allocated across variants.'
      : 'Public YODY catalog reference; source URL included.'
  };
}

async function main() {
  const records = readRecords();
  await connectMongo();
  let producerReady = false;
  try {
    const existing = await Product.find({ shopId: SHOP_ID, $or: [
      { sourceProvider: 'yody' }, { detail: /data-source="yody"/ }
    ] });
    const existingById = new Map(existing.map((product) =>
      [product.sourceProductId || product.detail.match(/data-source-id="(\d+)"/)?.[1], product]).filter(([id]) => id));
    const needsDefault = (product) => product.variants.length > 0 &&
      product.variants.every((variant) => Number(variant.quantity || 0) === 0);
    console.log(JSON.stringify({ mode: APPLY ? 'apply' : 'dry-run', input: INPUT,
      snapshot: records.length, alreadyImported: existingById.size,
      toInsert: records.filter((record) => !existingById.has(String(record.sourceId))).length,
      toDefaultStock: records.filter((record) => {
        const product = existingById.get(String(record.sourceId));
        return product && needsDefault(product);
      }).length }));
    if (!APPLY) return;
    await initProducer();
    producerReady = true;
    const categories = new Map();
    let inserted = 0;
    let defaulted = 0;
    for (const record of records) {
      const existingProduct = existingById.get(String(record.sourceId));
      if (existingProduct) {
        if (needsDefault(existingProduct)) {
          fillDefaultStock(existingProduct.variants);
          existingProduct.quantity = existingProduct.variants.reduce((sum, variant) => sum + variant.quantity, 0);
          existingProduct.moderationNote = 'Public YODY catalog reference; default demo stock 100 allocated across variants.';
          existingProduct.detail = existingProduct.detail.replace(
            '<p>Giá và tình trạng hàng là dữ liệu tham khảo tại thời điểm thu thập.</p>',
            '<p>Giá tham khảo từ nguồn; tồn kho mặc định 100 là dữ liệu nội bộ.</p>'
          );
          await existingProduct.save();
          await publishProductCreated(existingProduct);
          defaulted += 1;
          if (defaulted % 100 === 0) console.log(`Defaulted and published ${defaulted}`);
        } else if (RESYNC_STOCK) {
          await publishProductCreated(existingProduct);
        }
        continue;
      }
      if (!categories.has(record.categoryName)) {
        const name = `YODY · ${record.categoryName}`;
        const category = await Category.findOneAndUpdate(
          { name, shopId: SHOP_ID },
          { $setOnInsert: { description: `Sản phẩm thời trang tham khảo từ ${name}.` } },
          { new: true, upsert: true }
        );
        categories.set(record.categoryName, category._id);
      }
      const product = await Product.create(buildProduct(record, categories.get(record.categoryName)));
      await publishProductCreated(product);
      inserted += 1;
      if (inserted % 100 === 0) console.log(`Inserted and published ${inserted}`);
    }
    console.log(JSON.stringify({ inserted, defaulted, totalForSnapshot: records.length }));
  } finally {
    if (producerReady) await closeProducer();
    await mongoose.disconnect();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
