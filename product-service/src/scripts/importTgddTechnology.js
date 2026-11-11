/* Import the attributed TGDD research snapshot into the demo marketplace. */
const fs = require('node:fs');
const path = require('node:path');
const mongoose = require('mongoose');
const { connectMongo } = require('../config/db');
const Product = require('../models/Product');
const Category = require('../models/Category');
const { canonicalPath, ensureCategoryPath } = require('../utils/categoryTaxonomy');
const { initProducer, closeProducer, publishProductCreated, publishProductUpdated } = require('../kafka/producer');
const { normalizeObjectKey, uploadProductFile } = require('../services/objectStorage');

const INPUT = path.resolve(process.env.TGDD_IMPORT_INPUT || 'output/catalog/tgdd-technology-500.jsonl');
const SHOP_ID = process.env.TGDD_IMPORT_SHOP_ID;
const APPLY = process.argv.includes('--apply');
const REPAIR_SPECS = process.argv.includes('--repair-specs');
const REPAIR_IMAGES = process.argv.includes('--repair-images');
const CATEGORIES = ['Laptop', 'Điện thoại', 'Tai nghe', 'Loa'];
const DEMO_STOCK = 100;
const LEGACY_IMAGE_PREFIX = 'https://cdn.tgdd.vn/';
const MAX_IMAGE_BYTES = 15 * 1024 * 1024;

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

function hasLegacyTgddImage(images) {
  return Array.isArray(images) && images.some((image) => String(image).startsWith(LEGACY_IMAGE_PREFIX));
}

async function downloadTgddImage(imageUrl, sourceUrl) {
  const response = await fetch(imageUrl, {
    headers: {
      Accept: 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
      Referer: sourceUrl,
      'User-Agent': 'Mozilla/5.0 (compatible; ResearchCatalogBot/1.0; +https://example.org/research)'
    },
    redirect: 'follow'
  });
  if (!response.ok) {
    throw new Error(`TGDD image returned HTTP ${response.status}: ${imageUrl}`);
  }
  const mimetype = String(response.headers.get('content-type') || '').split(';', 1)[0].trim().toLowerCase();
  if (!mimetype.startsWith('image/')) {
    throw new Error(`TGDD image returned ${mimetype || 'an unknown content type'}: ${imageUrl}`);
  }
  const buffer = Buffer.from(await response.arrayBuffer());
  if (!buffer.length || buffer.length > MAX_IMAGE_BYTES) {
    throw new Error(`TGDD image has invalid size ${buffer.length}: ${imageUrl}`);
  }
  const originalname = path.basename(new URL(imageUrl).pathname) || 'image.jpg';
  return { buffer, mimetype, originalname };
}

async function localizeTgddImages(product) {
  const images = [];
  let uploaded = 0;
  for (const imageUrl of product.images || []) {
    if (!String(imageUrl).startsWith(LEGACY_IMAGE_PREFIX)) {
      images.push(imageUrl);
      continue;
    }
    const file = await downloadTgddImage(imageUrl, product.sourceUrl);
    const storedUrl = await uploadProductFile(file, `tgdd/${product.sourceProductId}`);
    images.push(`/uploads/${normalizeObjectKey(storedUrl)}`);
    uploaded += 1;
  }
  return { images, uploaded };
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
      { sourceProductId: 1, sourceUrl: 1, images: 1, specifications: 1 });
    const existingById = new Map(existing.map((item) => [item.sourceProductId, item]));
    const existingIds = new Set(existingById.keys());
    const toRepairImages = existing.filter((item) => hasLegacyTgddImage(item.images)).length;
    console.log(JSON.stringify({ mode: APPLY ? 'apply' : 'dry-run', snapshot: rows.length,
      existing: existingIds.size, toInsert: rows.filter((row) => !existingIds.has(String(row.sourceId))).length,
      toRepairImages: REPAIR_IMAGES ? toRepairImages : 0 }));
    if (!APPLY) return;
    await initProducer();
    producerReady = true;
    const categories = new Map();
    for (const name of CATEGORIES) {
      // Placed in the shared tree: Điện tử › Laptop, ...
      const category = await ensureCategoryPath(Category, canonicalPath(name), SHOP_ID, {
        description: `Sản phẩm công nghệ từ dữ liệu công khai, dùng cho nghiên cứu: ${name}.`
      });
      categories.set(name, category._id);
    }
    let inserted = 0;
    let repaired = 0;
    let repairedImages = 0;
    let uploadedImages = 0;
    for (const row of rows) {
      const previous = existingById.get(String(row.sourceId));
      if (previous) {
        const changes = {};
        if (REPAIR_SPECS) {
          const next = buildProduct(row, categories.get(row.category));
          const oldSpecs = previous.specifications.map(({ name, value }) => ({ name, value }));
          if (JSON.stringify(oldSpecs) !== JSON.stringify(next.specifications)) {
            changes.specifications = next.specifications;
            changes.detail = next.detail;
            repaired += 1;
          }
        }
        if (REPAIR_IMAGES && hasLegacyTgddImage(previous.images)) {
          const localized = await localizeTgddImages(previous);
          changes.images = localized.images;
          repairedImages += 1;
          uploadedImages += localized.uploaded;
          if (repairedImages % 10 === 0) {
            console.log(`Localized images for ${repairedImages} products (${uploadedImages} files)`);
          }
        }
        if (Object.keys(changes).length) {
          const product = await Product.findByIdAndUpdate(previous._id, { $set: changes }, { new: true });
          await publishProductUpdated(product);
        }
        continue;
      }
      const product = await Product.create(buildProduct(row, categories.get(row.category)));
      await publishProductCreated(product);
      existingIds.add(String(row.sourceId));
      inserted += 1;
      if (inserted % 25 === 0) console.log(`Inserted and published ${inserted}`);
    }
    console.log(JSON.stringify({ inserted, repaired, repairedImages, uploadedImages,
      total: rows.length, shopId: SHOP_ID }));
  } finally {
    if (producerReady) await closeProducer();
    await mongoose.disconnect();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
