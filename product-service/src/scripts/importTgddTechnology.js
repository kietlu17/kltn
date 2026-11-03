/* Import the attributed TGDD research snapshot into the demo marketplace. */
const fs = require('node:fs');
const path = require('node:path');
const mongoose = require('mongoose');
const { connectMongo } = require('../config/db');
const Product = require('../models/Product');
const Category = require('../models/Category');
const { initProducer, closeProducer, publishProductCreated, publishProductUpdated } = require('../kafka/producer');

const INPUT = path.resolve(process.env.TGDD_IMPORT_INPUT || 'output/catalog/tgdd-technology-500.jsonl');
const SHOP_ID = process.env.TGDD_IMPORT_SHOP_ID;
const APPLY = process.argv.includes('--apply');
const REPAIR_SPECS = process.argv.includes('--repair-specs');
const CATEGORIES = ['Laptop', 'Điện thoại', 'Tai nghe', 'Loa'];
const DEMO_STOCK = 100;

function readRecords() {
  const rows = fs.readFileSync(INPUT, 'utf8').split(/\r?\n/).filter(Boolean).map(JSON.parse);
  const ids = new Set();
  for (const row of rows) {
    const id = String(row.sourceId || '');
    if (!/^\d+$/.test(id) || ids.has(id) || !CATEGORIES.includes(row.category) ||
        !row.sourceUrl?.startsWith('https://www.thegioididong.com/') ||
        !row.name || row.description?.length < 180 ||
        Object.keys(row.specifications || {}).length < 5 || !row.images?.length ||
        !(row.price > 0) || row.originalPrice < row.price) {
      throw new Error(`Incomplete or duplicate TGDD product: ${id}`);
    }
    ids.add(id);
  }
  if (rows.length !== 500) throw new Error(`Expected 500 products, got ${rows.length}`);
  for (const category of CATEGORIES) {
    if (rows.filter((row) => row.category === category).length !== 125) {
      throw new Error(`Expected 125 products in ${category}`);
    }
  }
  return rows;
}

function buildProduct(row, categoryId) {
  const specs = Object.entries(row.specifications)
    .filter(([name, value]) => !/^\d{1,3}$/.test(String(value).trim()) || ['Số nhân', 'Số luồng'].includes(name))
    .map(([name, value]) => ({ name, value: String(value) }));
  const detail = [
    `Nguồn dữ liệu tham khảo: ${row.sourceUrl}`,
    `Thu thập: ${row.collectedAt}. Giá có thể thay đổi; tồn kho ${DEMO_STOCK} là dữ liệu mô phỏng.`,
    'Thông số kỹ thuật:',
    ...specs.map(({ name, value }) => `${name}: ${value}`)
  ].join('\n');
  return {
    name: row.name,
    originalPrice: row.originalPrice,
    price: row.price,
    description: row.description,
    detail,
    specifications: specs,
    sourceProvider: 'tgdd',
    sourceProductId: String(row.sourceId),
    sourceUrl: row.sourceUrl,
    images: row.images,
    quantity: DEMO_STOCK,
    sold: 0,
    variants: [],
    categoryId: String(categoryId),
    shopId: SHOP_ID,
    moderationStatus: 'approved',
    moderatedBy: 'tgdd-technology-research-import',
    moderatedAt: new Date(),
    moderationNote: 'Attributed public catalog snapshot for research; stock is simulated.'
  };
}

async function main() {
  if (!SHOP_ID || !mongoose.Types.ObjectId.isValid(SHOP_ID)) {
    throw new Error('Set TGDD_IMPORT_SHOP_ID to the research seller shop ID');
  }
  const rows = readRecords();
  await connectMongo();
  let producerReady = false;
  try {
    const existing = await Product.find({ shopId: SHOP_ID, sourceProvider: 'tgdd' },
      { sourceProductId: 1, specifications: 1 });
    const existingById = new Map(existing.map((item) => [item.sourceProductId, item]));
    const existingIds = new Set(existingById.keys());
    console.log(JSON.stringify({ mode: APPLY ? 'apply' : 'dry-run', snapshot: rows.length,
      existing: existingIds.size, toInsert: rows.filter((row) => !existingIds.has(String(row.sourceId))).length }));
    if (!APPLY) return;
    await initProducer();
    producerReady = true;
    const categories = new Map();
    for (const name of CATEGORIES) {
      const category = await Category.findOneAndUpdate(
        { name, shopId: SHOP_ID },
        { $setOnInsert: { description: `Sản phẩm công nghệ từ dữ liệu công khai, dùng cho nghiên cứu: ${name}.` } },
        { new: true, upsert: true }
      );
      categories.set(name, category._id);
    }
    let inserted = 0;
    let repaired = 0;
    for (const row of rows) {
      const previous = existingById.get(String(row.sourceId));
      if (previous) {
        if (REPAIR_SPECS) {
          const next = buildProduct(row, categories.get(row.category));
          const oldSpecs = previous.specifications.map(({ name, value }) => ({ name, value }));
          if (JSON.stringify(oldSpecs) !== JSON.stringify(next.specifications)) {
            const product = await Product.findByIdAndUpdate(previous._id,
              { $set: { specifications: next.specifications, detail: next.detail } }, { new: true });
            await publishProductUpdated(product);
            repaired += 1;
          }
        }
        continue;
      }
      const product = await Product.create(buildProduct(row, categories.get(row.category)));
      await publishProductCreated(product);
      existingIds.add(String(row.sourceId));
      inserted += 1;
      if (inserted % 25 === 0) console.log(`Inserted and published ${inserted}`);
    }
    console.log(JSON.stringify({ inserted, repaired, total: rows.length, shopId: SHOP_ID }));
  } finally {
    if (producerReady) await closeProducer();
    await mongoose.disconnect();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
