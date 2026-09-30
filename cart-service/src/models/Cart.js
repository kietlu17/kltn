const mongoose = require('mongoose');

const cartSchema = new mongoose.Schema(
  {
    userId: { type: String, required: true, unique: true },
    products: [
      {
        productId: { type: String, required: true },
        variantId: { type: String, default: null },
        quantity: { type: Number, required: true }
      }
    ],
    processedActions: {
      type: [
        {
          key: { type: String, required: true },
          productId: { type: String, required: true },
          variantId: { type: String, default: null },
          quantity: { type: Number, required: true },
          processedAt: { type: Date, default: Date.now }
        }
      ],
      default: []
    }
  },
  { timestamps: true }
);

module.exports = mongoose.model('Cart', cartSchema);
