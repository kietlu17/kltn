const mongoose = require('mongoose');

const productSalesEventSchema = new mongoose.Schema(
  {
    orderId: { type: String, required: true, unique: true, index: true },
    status: {
      type: String,
      enum: ['processing', 'processed', 'failed'],
      default: 'processing',
      index: true
    },
    itemCount: { type: Number, default: 0 },
    totalQuantity: { type: Number, default: 0 },
    processedAt: { type: Date, default: null },
    lastError: { type: String, default: '' },
    payload: { type: mongoose.Schema.Types.Mixed, default: null }
  },
  { timestamps: true }
);

module.exports = mongoose.model('ProductSalesEvent', productSalesEventSchema);
