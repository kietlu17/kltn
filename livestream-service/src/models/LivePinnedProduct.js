const mongoose = require('mongoose');

const livePinnedProductSchema = new mongoose.Schema(
  {
    liveId: { type: String, required: true, index: true },
    shopId: { type: String, required: true, index: true },
    productId: { type: String, required: true, index: true },
    nameSnapshot: { type: String, required: true },
    priceSnapshot: { type: Number, default: 0 },
    imageSnapshot: { type: String, default: '' },
    stockSnapshot: { type: Number, default: 0 },
    sortOrder: { type: Number, default: 0 },
    isActive: { type: Boolean, default: false },
    pinnedAt: { type: Date, default: Date.now },
    unpinnedAt: { type: Date, default: null }
  },
  { timestamps: true }
);

livePinnedProductSchema.index({ liveId: 1, productId: 1 }, { unique: true });
livePinnedProductSchema.index({ liveId: 1, isActive: 1 });

module.exports = mongoose.model('LivePinnedProduct', livePinnedProductSchema);
