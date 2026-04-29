const mongoose = require('mongoose');

const userProfileSchema = new mongoose.Schema(
  {
    userId: { type: String, required: true, unique: true },
    name: { type: String, default: '' },
    address: { type: String, default: '' },
    addresses: {
      type: [
        {
          label: { type: String, default: '' },
          fullName: { type: String, default: '' },
          phone: { type: String, default: '' },
          line1: { type: String, default: '' },
          line2: { type: String, default: '' },
          city: { type: String, default: '' },
          state: { type: String, default: '' },
          postalCode: { type: String, default: '' },
          country: { type: String, default: '' },
          isDefault: { type: Boolean, default: false }
        }
      ],
      default: []
    },
    phone: { type: String, default: '' }
  },
  { timestamps: true }
);

module.exports = mongoose.model('UserProfile', userProfileSchema);
