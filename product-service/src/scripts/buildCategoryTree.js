/*
 * Turn the flat, source-prefixed categories into one category tree:
 * Chủng loại -> Chủng loại con -> ... -> Sản phẩm.
 *
 *   node src/scripts/buildCategoryTree.js            # dry run: print the plan
 *   node src/scripts/buildCategoryTree.js --apply    # write it (backup first)
 *   node src/scripts/buildCategoryTree.js --restore <backup.json>
 *
 * Non-destructive: no product changes category and no seller category is
 * deleted. Shared ancestors (Thời trang, Thời trang › Nữ, Điện tử, ...) are
 * created as platform nodes; each seller category gets parentId, path, level,
 * a clean name ("YODY · Áo thun nữ" -> "Áo thun nữ") and keeps its original
 * name in sourceName, so the script can be re-run or undone.
 * Re-index the assistant catalog afterwards (python -m app.indexer).
 */
const fs = require('node:fs');
const path = require('node:path');
const mongoose = require('mongoose');
const { connectMongo } = require('../config/db');
const Category = require('../models/Category');
const { PLATFORM_SHOP_ID, canonicalPath, joinPath } = require('../utils/categoryTaxonomy');

const APPLY = process.argv.includes('--apply');
const RESTORE = process.argv.includes('--restore') ? process.argv[process.argv.indexOf('--restore') + 1] : '';
const BACKUP_DIR = path.resolve(process.env.CATEGORY_BACKUP_DIR || 'output/catalog');

/**
 * Pure planner, exported for tests: which platform nodes to create and what
 * every seller category becomes. Ids of planned platform nodes are "new:<path>".
 */
function planTree(categories) {
  const sellers = categories.filter((item) => item.shopId !== PLATFORM_SHOP_ID);
  const platformByPath = new Map(
    categories
      .filter((item) => item.shopId === PLATFORM_SHOP_ID && item.path)
      .map((item) => [item.path, String(item._id)])
  );
  const planned = sellers
    .map((item) => ({ item, segments: canonicalPath(item.sourceName || item.name) }))
    .filter(({ segments }) => segments.length)
    .sort((a, b) => a.segments.length - b.segments.length);
  // A seller category may also be an intermediate level of the same seller
  // ("YODY · Nam" is the parent of "YODY · Áo thun nam").
  const sellerByPath = new Map();
  for (const { item, segments } of planned) {
    const keyPath = `${item.shopId}|${joinPath(segments)}`;
    if (!sellerByPath.has(keyPath)) sellerByPath.set(keyPath, String(item._id));
  }
  const create = [];
  function platformNode(segments) {
    const nodePath = joinPath(segments);
    if (platformByPath.has(nodePath)) return platformByPath.get(nodePath);
    const parentId = segments.length > 1 ? platformNode(segments.slice(0, -1)) : null;
    const id = `new:${nodePath}`;
    create.push({ id, name: segments[segments.length - 1], parentId, path: nodePath, level: segments.length - 1 });
    platformByPath.set(nodePath, id);
    return id;
  }
  function parentOf(shopId, segments) {
    if (segments.length === 1) return null;
    const parentSegments = segments.slice(0, -1);
    // Roots are always platform nodes; below them the shop's own category
    // at that position beats a platform node.
    const own = parentSegments.length > 1 && sellerByPath.get(`${shopId}|${joinPath(parentSegments)}`);
    return own || platformNode(parentSegments);
  }
  const update = planned.map(({ item, segments }) => ({
    id: String(item._id),
    shopId: item.shopId,
    sourceName: item.sourceName || item.name,
    name: segments[segments.length - 1],
    parentId: parentOf(item.shopId, segments),
    path: joinPath(segments),
    level: segments.length - 1
  }));
  return { create, update };
}

async function restore(file) {
  const backup = JSON.parse(fs.readFileSync(file, 'utf8'));
  const original = new Set(backup.map((item) => String(item._id)));
  for (const item of backup) {
    await Category.updateOne(
      { _id: item._id },
      { $set: { name: item.name, parentId: item.parentId ?? null, path: item.path ?? '', level: item.level ?? 0, sourceName: item.sourceName ?? '' } }
    );
  }
  const removed = await Category.deleteMany({ shopId: PLATFORM_SHOP_ID, _id: { $nin: [...original] } });
  console.log(JSON.stringify({ restored: backup.length, removedPlatformNodes: removed.deletedCount }));
}

async function main() {
  await connectMongo();
  try {
    if (RESTORE) return await restore(path.resolve(RESTORE));
    const categories = await Category.find({}).lean();
    const { create, update } = planTree(categories);
    const roots = {};
    for (const item of update) roots[item.path.split(' › ')[0]] = (roots[item.path.split(' › ')[0]] || 0) + 1;
    console.log(JSON.stringify({
      mode: APPLY ? 'apply' : 'dry-run',
      categories: categories.length,
      platformNodesToCreate: create.length,
      sellerCategoriesToUpdate: update.length,
      sellerCategoriesPerRoot: roots
    }, null, 2));
    for (const item of update.slice(0, 400)) console.log(`  ${item.path}   <=  ${item.sourceName}`);
    if (!APPLY) return;

    fs.mkdirSync(BACKUP_DIR, { recursive: true });
    const backupFile = path.join(BACKUP_DIR, `categories-backup-${Date.now()}.json`);
    fs.writeFileSync(backupFile, JSON.stringify(categories, null, 2));
    console.log(`Backup: ${backupFile}`);

    const ids = new Map();
    const resolve = (id) => (id && String(id).startsWith('new:') ? ids.get(id) : id) || null;
    for (const node of create) {
      const saved = await Category.findOneAndUpdate(
        { shopId: PLATFORM_SHOP_ID, parentId: resolve(node.parentId), name: node.name },
        { $set: { path: node.path, level: node.level }, $setOnInsert: { description: '' } },
        { upsert: true, new: true, setDefaultsOnInsert: true }
      );
      ids.set(node.id, String(saved._id));
    }
    for (const item of update) {
      await Category.updateOne(
        { _id: item.id },
        { $set: { name: item.name, parentId: resolve(item.parentId), path: item.path, level: item.level, sourceName: item.sourceName } }
      );
    }
    console.log(JSON.stringify({ createdPlatformNodes: create.length, updatedSellerCategories: update.length }));
  } finally {
    await mongoose.disconnect();
  }
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}

module.exports = { planTree };
