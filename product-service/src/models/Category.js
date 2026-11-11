const mongoose = require('mongoose');

const categorySchema = new mongoose.Schema(
  {
    name: { type: String, required: true },
    description: { type: String, default: '' },
    // A seller's own categories carry the seller's shopId. Shared browse
    // nodes (Thời trang › Nữ, Điện tử, ...) belong to the platform.
    shopId: { type: String, required: true },
    // Category tree: Chủng loại -> Chủng loại con -> ... -> Sản phẩm.
    parentId: { type: String, default: null, index: true },
    // Denormalized display path ("Thời trang › Nữ › Áo thun nữ") and depth
    // (0 = root), kept in sync by utils/categoryTaxonomy.
    path: { type: String, default: '' },
    level: { type: Number, default: 0 },
    // Name before the taxonomy migration, so it can be re-run or undone.
    sourceName: { type: String, default: '' }
  },
  { timestamps: true }
);

module.exports = mongoose.model('Category', categorySchema);
