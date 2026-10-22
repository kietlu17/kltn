/* Import a category-balanced MUJI Vietnam snapshot into the demo catalog. */
const fs = require('node:fs');
const path = require('node:path');
const mongoose = require('mongoose');
const { connectMongo } = require('../config/db');
const Product = require('../models/Product');
const Category = require('../models/Category');
const { initProducer, closeProducer, publishProductCreated } = require('../kafka/producer');

const SHOP_ID = process.env.MUJI_IMPORT_SHOP_ID || '69f1b1cb00f071907a7e0fd4';
const INPUT = path.resolve(process.env.MUJI_IMPORT_INPUT || 'output/catalog/muji-diverse-1000.jsonl');
const LIMIT = Number(process.env.MUJI_IMPORT_LIMIT || 1000);
const APPLY = process.argv.includes('--apply');
const DEFAULT_STOCK = 100;

function escapeHtml(value) {
  return String(value || '').replaceAll('&', '&amp;').replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

function readRecords() {
  const rows = fs.readFileSync(INPUT, 'utf8').split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line));
  const ids = new Set();
  for (const row of rows) {
    const id = String(row.sourceId || '');
    if (!/^\d+$/.test(id) || ids.has(id) ||
        !row.sourceUrl?.startsWith('https://www.muji.com.vn/vn/product/') ||
        !row.name || !row.department || !row.categoryPath || !row.description ||
        !row.sourceDetail || !row.images?.length || !row.variants?.length || !(row.price > 0) ||
        row.images.some((url) => /\/placeholder\//i.test(url)) ||
        row.variants.some((variant) => /\/placeholder\//i.test(variant.imageUrl || ''))) {
      throw new Error(`Invalid or duplicate MUJI record: ${id}`);
    }
    ids.add(id);
  }
  if (rows.length < LIMIT) throw new Error(`Snapshot has ${rows.length}/${LIMIT} MUJI products`);
  return rows.slice(0, LIMIT);
}

function fillDefaultStock(variants) {
  if (variants.some((variant) => Number(variant.quantity || 0) > 0)) return false;
  const perVariant = Math.floor(DEFAULT_STOCK / variants.length);
  const remainder = DEFAULT_STOCK % variants.length;
  variants.forEach((variant, index) => {
    variant.quantity = perVariant + (index < remainder ? 1 : 0);
  });
  return true;
}

function buildProduct(row, categoryId) {
  const variants = row.variants.map((variant) => ({
    name: variant.name,
    sku: variant.sku,
    imageUrl: variant.imageUrl,
    originalPrice: variant.originalPrice,
    price: variant.price,
    quantity: variant.quantity
  }));
  const defaulted = fillDefaultStock(variants);
  const stockNote = defaulted
    ? 'Tồn kho mặc định 100 là dữ liệu nội bộ, được chia giữa các biến thể.'
    : 'Tồn kho tham khảo từ dữ liệu sản phẩm công khai tại thời điểm thu thập.';
  const detail = [
    `Danh mục: ${row.categoryPath}.`,
    stockNote,
    `Nguồn: ${row.sourceUrl}`
  ].join('\n');
  return {
    name: row.name,
    originalPrice: row.originalPrice,
    price: row.price,
    description: row.sourceDetail || row.description,
    detail,
    sourceProvider: 'muji',
    sourceProductId: String(row.sourceId),
    sourceUrl: row.sourceUrl,
    images: row.images,
    quantity: variants.reduce((sum, variant) => sum + variant.quantity, 0),
    sold: 0,
    variants,
    categoryId: String(categoryId),
    shopId: SHOP_ID,
    moderationStatus: 'approved',
    moderatedBy: 'muji-catalog-import',
    moderatedAt: new Date(),
    moderationNote: defaulted
      ? 'Public MUJI catalog reference; default demo stock 100 allocated across variants.'
      : 'Public MUJI catalog reference; source URL and source stock included.'
  };
}

async function main() {
  const records = readRecords();
  await connectMongo();
  let producerReady = false;
  try {
    const existing = await Product.find({ shopId: SHOP_ID, $or: [
      { sourceProvider: 'muji' }, { detail: /data-source="muji"/ }
    ] }, { detail: 1, sourceProductId: 1 });
    const existingIds = new Set(existing.map((product) =>
      product.sourceProductId || product.detail.match(/data-source-id="(\d+)"/)?.[1]).filter(Boolean));
    console.log(JSON.stringify({ mode: APPLY ? 'apply' : 'dry-run', snapshot: records.length,
      alreadyImported: existingIds.size,
      toInsert: records.filter((record) => !existingIds.has(String(record.sourceId))).length }));
    if (!APPLY) return;
    await initProducer();
    producerReady = true;
    const categories = new Map();
    let inserted = 0;
    for (const row of records) {
      if (existingIds.has(String(row.sourceId))) continue;
      if (!categories.has(row.categoryPath)) {
        const name = `MUJI · ${row.categoryPath}`;
        const category = await Category.findOneAndUpdate(
          { name, shopId: SHOP_ID },
          { $setOnInsert: { description: `Sản phẩm tham khảo từ MUJI Việt Nam: ${row.categoryPath}.` } },
          { new: true, upsert: true }
        );
        categories.set(row.categoryPath, category._id);
      }
      const product = await Product.create(buildProduct(row, categories.get(row.categoryPath)));
      await publishProductCreated(product);
      existingIds.add(String(row.sourceId));
      inserted += 1;
      if (inserted % 100 === 0) console.log(`Inserted and published ${inserted}`);
    }
    console.log(JSON.stringify({ inserted, totalForSnapshot: records.length }));
  } finally {
    if (producerReady) await closeProducer();
    await mongoose.disconnect();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
