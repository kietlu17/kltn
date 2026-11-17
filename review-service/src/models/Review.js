const mongoose = require('mongoose');

const reviewSchema = new mongoose.Schema(
  {
    productId: { type: String, required: true },
    userId: { type: String, required: true },
    userName: { type: String, default: 'Anonymous' },
    rating: { type: Number, min: 1, max: 5, required: true },
    comment: { type: String, default: '' },
    // 'user' for reviews written in the shop, 'seed' for generated demo data
    // (scripts/seed-reviews.js), so seeded rows can be removed at once.
    source: { type: String, enum: ['user', 'seed'], default: 'user' }
  },
  { timestamps: true }
);

reviewSchema.index({ productId: 1, userId: 1 }, { unique: true });
reviewSchema.index({ productId: 1, createdAt: -1 });

module.exports = mongoose.model('Review', reviewSchema);
