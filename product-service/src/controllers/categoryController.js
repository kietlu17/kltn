const Category = require('../models/Category');

async function createCategory(req, res) {
  try {
    const { name, description, shopId } = req.body;
    if (!name || !shopId) {
      return res.status(400).json({ message: 'name and shopId are required' });
    }
    const category = await Category.create({ name, description, shopId });
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
    const { name, description, shopId } = req.body;
    if (!shopId) {
      return res.status(400).json({ message: 'shopId is required' });
    }
    const updates = {};
    if (name != null) updates.name = name;
    if (description != null) updates.description = description;
    const category = await Category.findOneAndUpdate(
      { _id: req.params.id, shopId },
      updates,
      { new: true }
    );
    if (!category) {
      return res.status(404).json({ message: 'Category not found' });
    }
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
    const category = await Category.findByIdAndUpdate(req.params.id, updates, { new: true });
    if (!category) {
      return res.status(404).json({ message: 'Category not found' });
    }
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
