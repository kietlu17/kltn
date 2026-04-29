const Product = require('../models/Product');

async function backfillModerationStatus() {
  const result = await Product.updateMany(
    { moderationStatus: { $exists: false } },
    {
      $set: {
        moderationStatus: 'approved',
        moderatedBy: 'system-backfill',
        moderatedAt: new Date(),
        moderationNote: 'Backfilled from legacy product data'
      }
    }
  );
  const count = result?.modifiedCount || 0;
  if (count > 0) {
    console.log(`Product moderation backfill updated ${count} documents`);
  }
}

module.exports = { backfillModerationStatus };
