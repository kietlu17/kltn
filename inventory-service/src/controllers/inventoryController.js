const Inventory = require('../models/Inventory');

async function getInventory(req, res) {
  try {
    const productId = req.params.productId;
    const record = await Inventory.findOne({ where: { product_id: productId } });
    if (!record) {
      return res.status(404).json({ message: 'Inventory not found' });
    }
    return res.json(record.toJSON());
  } catch (err) {
    return res.status(500).json({ message: 'Get inventory failed', error: err.message });
  }
}

async function updateInventory(req, res) {
  try {
    const productId = req.params.productId;
    const { stock, reservedStock } = req.body;
    const record = await Inventory.findOne({ where: { product_id: productId } });
    if (!record) {
      return res.status(404).json({ message: 'Inventory not found' });
    }
    record.stock = Number(stock || 0);
    record.reserved_stock = Number(reservedStock || 0);
    await record.save();
    return res.json(record.toJSON());
  } catch (err) {
    return res.status(500).json({ message: 'Update inventory failed', error: err.message });
  }
}

module.exports = { getInventory, updateInventory };
