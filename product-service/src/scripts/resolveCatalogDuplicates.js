/* Hide single-variant MUJI records already represented in multi-variant records. */
const mongoose = require('mongoose');
const { connectMongo } = require('../config/db');
const Product = require('../models/Product');

const PAIRS = [
  { sku: '4550723183758', single: '6ad8d277ea17586d6ca099ff', multi: '6ad8d278ea17586d6ca0a007' },
  { sku: '4550583830397', single: '6ad8d278ea17586d6ca09c3e', multi: '6ad8d278ea17586d6ca09f16' }
];
const APPLY = process.argv.includes('--apply');

async function main() {
  await connectMongo();
  try {
    for (const pair of PAIRS) {
      const [single, multi] = await Promise.all([
        Product.findById(pair.single), Product.findById(pair.multi)
      ]);
      if (!single || !multi) throw new Error(`Missing duplicate pair ${pair.sku}`);
      if (single.moderationStatus === 'removed') {
        console.log(JSON.stringify({ sku: pair.sku, status: 'already-removed' }));
        continue;
      }
      const matching = multi.variants.find((variant) => variant.sku === pair.sku);
      if (single.moderationStatus !== 'approved' || multi.moderationStatus !== 'approved' ||
          single.variants.length !== 1 || single.variants[0].sku !== pair.sku ||
          multi.variants.length < 2 || !matching ||
          single.shopId !== multi.shopId || single.categoryId !== multi.categoryId ||
          single.price !== multi.price || single.sold !== 0 || multi.sold !== 0 ||
          single.variants[0].quantity !== matching.quantity) {
        throw new Error(`Duplicate pair changed or no longer safe to consolidate: ${pair.sku}`);
      }
      const gallery = [...new Set([...multi.images, ...single.images])];
      console.log(JSON.stringify({ sku: pair.sku, single: pair.single, multi: pair.multi,
        singleImages: single.images.length, combinedImages: gallery.length,
        stockKept: matching.quantity, mode: APPLY ? 'apply' : 'dry-run' }));
      if (!APPLY) continue;
      multi.images = gallery;
      await multi.save();
      single.moderationStatus = 'removed';
      single.moderatedBy = 'catalog-dedup-cleanup';
      single.moderatedAt = new Date();
      single.moderationNote = `Duplicate variant SKU ${pair.sku}; use product ${pair.multi}.`;
      await single.save();
    }
  } finally {
    await mongoose.disconnect();
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
