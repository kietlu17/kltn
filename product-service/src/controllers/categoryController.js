const Category = require('../models/Category');
const { descendantIds, pathFields, refreshDescendantPaths } = require('../utils/categoryTaxonomy');

// parentId: '' or null makes a root. The parent must exist and must not be
// the category itself or one of its descendants.
async function placement(name, parentId, categoryId = null) {
  const parent = parentId ? String(parentId) : null;
  if (parent && categoryId && (await descendantIds(Category, categoryId)).includes(parent)) {
    return { error: 'A category cannot be placed under itself or its descendants' };
  }
  const fields = await pathFields(Category, name, parent);
  return fields || { error: 'Parent category not found' };
}

async function createCategory(req, res) {
  try {
    const { name, description, shopId, parentId } = req.body;
    if (!name || !shopId) {
      return res.status(400).json({ message: 'name and shopId are required' });
    }
    const placed = await placement(name, parentId);
    if (placed.error) return res.status(400).json({ message: placed.error });
    const category = await Category.create({ name, description, shopId, ...placed });
    return res.status(201).json(category);
  } catch (err) {
    return res.status(500).json({ message: 'Create category failed', error: err.message });
  }
}

async function getCategories(req, res) {
  try {
    const { shopId } = req.query;
    const filter = shopId ? { shopId } : {};
    const categories = await Category.find(filter).sort({ createdAt: -1 });
    return res.json(categories);
  } catch (err) {
    return res.status(500).json({ message: 'Get categories failed', error: err.message });
  }
}

async function getCategoryById(req, res) {
  try {
    const category = await Category.findById(req.params.id);
    if (!category) {
      return res.status(404).json({ message: 'Category not found' });
    }
    return res.json(category);
  } catch (err) {
    return res.status(500).json({ message: 'Get category failed', error: err.message });
  }
}

async function updateCategory(req, res) {
  try {
    const { name, description, shopId, parentId } = req.body;
    if (!shopId) {
      return res.status(400).json({ message: 'shopId is required' });
    }
    const updates = {};
    if (name != null) updates.name = name;
    if (description != null) updates.description = description;
    if (parentId !== undefined || name != null) {
      const current = await Category.findOne({ _id: req.params.id, shopId }).lean();
      if (!current) {
        return res.status(404).json({ message: 'Category not found' });
      }
      const placed = await placement(
        name ?? current.name, parentId !== undefined ? parentId : current.parentId, req.params.id
      );
      if (placed.error) return res.status(400).json({ message: placed.error });
      Object.assign(updates, placed);
    }
    const category = await Category.findOneAndUpdate(
      { _id: req.params.id, shopId },
      updates,
      { new: true }
    );
    if (!category) {
      return res.status(404).json({ message: 'Category not found' });
    }
    if (updates.path) await refreshDescendantPaths(Category, category._id);
    return res.json(category);
  } catch (err) {
    return res.status(500).json({ message: 'Update category failed', error: err.message });
  }
}

async function deleteCategory(req, res) {
  try {
    const { shopId } = req.query;
    if (!shopId) {
      return res.status(400).json({ message: 'shopId is required' });
    }
    const category = await Category.findOneAndDelete({ _id: req.params.id, shopId });
    if (!category) {
      return res.status(404).json({ message: 'Category not found' });
    }
    return res.json({ message: 'Category deleted' });
  } catch (err) {
    return res.status(500).json({ message: 'Delete category failed', error: err.message });
  }
}

async function getAdminCategories(req, res) {
  try {
    const { q } = req.query;
    const filter = {};
    if (q) filter.name = { $regex: q, $options: 'i' };
    const categories = await Category.find(filter).sort({ createdAt: -1 });
    return res.json(categories);
  } catch (err) {
    return res.status(500).json({ message: 'Get admin categories failed', error: err.message });
  }
}

async function updateAdminCategory(req, res) {
  try {
    const updates = {};
    if (req.body?.name != null) updates.name = req.body.name;
    if (req.body?.description != null) updates.description = req.body.description;
    if (req.body?.shopId != null) updates.shopId = req.body.shopId;
    if (req.body?.name != null || req.body?.parentId !== undefined) {
      const current = await Category.findById(req.params.id).lean();
      if (!current) {
        return res.status(404).json({ message: 'Category not found' });
      }
      const placed = await placement(
        req.body?.name ?? current.name,
        req.body?.parentId !== undefined ? req.body.parentId : current.parentId,
        req.params.id
      );
      if (placed.error) return res.status(400).json({ message: placed.error });
      Object.assign(updates, placed);
    }
    const category = await Category.findByIdAndUpdate(req.params.id, updates, { new: true });
    if (!category) {
      return res.status(404).json({ message: 'Category not found' });
    }
    if (updates.path) await refreshDescendantPaths(Category, category._id);
    return res.json(category);
  } catch (err) {
    return res.status(500).json({ message: 'Update admin category failed', error: err.message });
  }
}

async function deleteAdminCategory(req, res) {
  try {
    const category = await Category.findByIdAndDelete(req.params.id);
    if (!category) {
      return res.status(404).json({ message: 'Category not found' });
    }
    return res.json({ message: 'Category deleted' });
  } catch (err) {
    return res.status(500).json({ message: 'Delete admin category failed', error: err.message });
  }
}

module.exports = {
  createCategory,
  getCategories,
  getCategoryById,
  updateCategory,
  deleteCategory,
  getAdminCategories,
  updateAdminCategory,
  deleteAdminCategory
};
