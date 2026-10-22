/* Apply a reviewed catalog cleanup plan after checking every original record. */
const fs = require('node:fs');
const path = require('node:path');
const mongoose = require('mongoose');
const { connectMongo } = require('../config/db');
const Product = require('../models/Product');

const ROOT = path.resolve(__dirname, '../../..');
const BEFORE = path.join(ROOT, 'output/catalog/catalog-before-dedup-cleanup.jsonl');
const PLAN = path.join(ROOT, 'output/catalog/catalog-cleanup-plan.jsonl');
const APPLY = process.argv.includes('--apply');

function readJsonl(file) {
  return fs.readFileSync(file, 'utf8').split(/\r?\n/).filter(Boolean).map(JSON.parse);
}

async function main() {
  const before = readJsonl(BEFORE);
  const plan = readJsonl(PLAN);
  const original = new Map(before.map((row) => [row._id, row]));
  if (original.size !== before.length || plan.length !== before.length ||
      new Set(plan.map((row) => row._id)).size !== plan.length) {
    throw new Error('Backup and plan must contain the same unique product IDs');
  }
  if (plan.some((row) => !original.has(row._id) ||
      /<\/?[a-z][^>]*>/i.test(`${row.description}\n${row.detail}`) ||
      (row.description && row.detail.includes(row.description)))) {
    throw new Error('Plan contains an unknown ID, HTML, or repeated description');
  }

  await connectMongo();
  try {
    const current = await Product.find({}, { _id: 1, description: 1, detail: 1 }).lean();
    if (current.length !== before.length || current.some((row) => {
      const saved = original.get(String(row._id));
      return !saved || row.description !== saved.description || row.detail !== saved.detail;
    })) {
      throw new Error('Catalog has changed since backup; rebuild the cleanup plan');
    }
    console.log(JSON.stringify({ mode: APPLY ? 'apply' : 'dry-run', checked: current.length }));
    if (!APPLY) return;

    let modified = 0;
    for (let offset = 0; offset < plan.length; offset += 200) {
      const operations = plan.slice(offset, offset + 200).map((row) => {
        const saved = original.get(row._id);
        return { updateOne: {
          filter: { _id: new mongoose.Types.ObjectId(row._id),
            description: saved.description, detail: saved.detail },
          update: { $set: {
            description: row.description,
            detail: row.detail,
            sourceProvider: row.sourceProvider,
            sourceProductId: row.sourceProductId,
            sourceUrl: row.sourceUrl,
            contentVersion: row.contentVersion
          }, $currentDate: { updatedAt: true } }
        } };
      });
      const result = await Product.collection.bulkWrite(operations, { ordered: true });
      if (result.matchedCount !== operations.length) {
        throw new Error(`Only matched ${result.matchedCount}/${operations.length} products at offset ${offset}`);
      }
      modified += result.modifiedCount;
    }
    console.log(JSON.stringify({ checked: current.length, modified }));
  } finally {
    await mongoose.disconnect();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
