const mongoose = require('mongoose');

const shopSchema = new mongoose.Schema(
  {
    name: { type: String, required: true },
    ownerId: { type: String, required: true },
    description: { type: String, default: '' },
    invoiceEligible: { type: Boolean, default: true },
    invoiceRequestMode: {
      type: String,
      enum: ['checkout_form', 'chat_required', 'off'],
      default: 'chat_required'
    },
    legalEntityType: {
      type: String,
      enum: ['company', 'business_household', 'individual', 'unknown'],
      default: 'unknown'
    },
    taxCode: { type: String, default: '' },
    invoiceProvider: { type: String, default: '' },
    invoiceFeatureStatus: {
      type: String,
      enum: ['active', 'off', 'pending_review', 'rejected'],
      default: 'active'
    },
    invoiceFeatureRequests: {
      type: [
        {
          requestedMode: {
            type: String,
            enum: ['checkout_form', 'chat_required', 'off'],
            required: true
          },
          reason: { type: String, default: '' },
          status: {
            type: String,
            enum: ['pending', 'approved', 'rejected'],
            default: 'pending'
          },
          adminNote: { type: String, default: '' },
          requestedBy: { type: String, default: '' },
          reviewedBy: { type: String, default: '' },
          requestedAt: { type: Date, default: Date.now },
          reviewedAt: { type: Date, default: null }
        }
      ],
      default: []
    }
  },
  { timestamps: true }
);

module.exports = mongoose.model('Shop', shopSchema);
