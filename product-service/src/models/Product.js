const mongoose = require('mongoose');

const variantSchema = new mongoose.Schema(
  {
    name: { type: String, required: true },
    sku: { type: String, default: '' },
    imageUrl: { type: String, default: '' },
    originalPrice: { type: Number, default: 0 },
    price: { type: Number, required: true },
    quantity: { type: Number, default: 0 }
  },
  { _id: true }
);

const productSchema = new mongoose.Schema(
  {
    name: { type: String, required: true },
    originalPrice: { type: Number, default: 0 },
    price: { type: Number, required: true },
    description: { type: String, default: '' },
    detail: { type: String, default: '' },
    sourceProvider: { type: String, default: '' },
    sourceProductId: { type: String, default: '' },
    sourceUrl: { type: String, default: '' },
    contentVersion: { type: String, default: '' },
    images: [{ type: String }],
    quantity: { type: Number, default: 0 },
    sold: { type: Number, default: 0, min: 0 },
    variants: { type: [variantSchema], default: [] },
    categoryId: { type: String, default: null },
    shopId: { type: String, required: true },
    moderationStatus: {
      type: String,
      enum: ['pending', 'approved', 'rejected', 'removed'],
      default: 'pending'
    },
    moderatedBy: { type: String, default: null },
    moderatedAt: { type: Date, default: null },
    moderationNote: { type: String, default: '' },
    strikeCount: { type: Number, default: 0 },
    lastStrikeReason: { type: String, default: '' }
  },
  { timestamps: true }
);

module.exports = mongoose.model('Product', productSchema);
