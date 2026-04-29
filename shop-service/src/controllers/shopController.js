const Shop = require('../models/Shop');

async function createShop(req, res) {
  try {
    const { name, ownerId, description } = req.body;
    if (!name || !ownerId) {
      return res.status(400).json({ message: 'name and ownerId are required' });
    }
    const shop = await Shop.create({ name, ownerId, description });
    return res.status(201).json(shop);
  } catch (err) {
    return res.status(500).json({ message: 'Create shop failed', error: err.message });
  }
}

async function getShops(req, res) {
  try {
    const shops = await Shop.find();
    return res.json(shops);
  } catch (err) {
    return res.status(500).json({ message: 'Get shops failed', error: err.message });
  }
}

async function getShopById(req, res) {
  try {
    const shop = await Shop.findById(req.params.id);
    if (!shop) {
      return res.status(404).json({ message: 'Shop not found' });
    }
    return res.json(shop);
  } catch (err) {
    return res.status(500).json({ message: 'Get shop failed', error: err.message });
  }
}

module.exports = { createShop, getShops, getShopById };
