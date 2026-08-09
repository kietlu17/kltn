const { sequelize } = require('../config/db');
const Inventory = require('../models/Inventory');
const InventoryReservation = require('../models/InventoryReservation');

function normalizeVariantId(value) {
  return value == null || value === '' ? '' : String(value);
}

function toInt(value, fallback = 0) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.trunc(number);
}

function toPublicInventory(record) {
  const value = record?.toJSON ? record.toJSON() : record;
  const stockOnHand = toInt(value.stock_on_hand);
  const reservedStock = toInt(value.reserved_stock);
  return {
    id: value.id,
    productId: value.product_id,
    variantId: value.variant_id || null,
    shopId: value.shop_id || null,
    sku: value.sku || '',
    stockOnHand,
    reservedStock,
    availableStock: Math.max(0, stockOnHand - reservedStock),
    createdAt: value.created_at || null,
    updatedAt: value.updated_at || null
  };
}

function normalizeItems(items) {
  if (!Array.isArray(items) || items.length === 0) {
    const err = new Error('items are required');
    err.status = 400;
    throw err;
  }
  return items.map((item) => {
    const productId = String(item?.productId || item?.product_id || '').trim();
    const variantId = normalizeVariantId(item?.variantId ?? item?.variant_id);
    const quantity = toInt(item?.quantity, NaN);
    if (!productId || !Number.isFinite(quantity) || quantity <= 0) {
      const err = new Error('invalid item data');
      err.status = 400;
      throw err;
    }
    return { productId, variantId, quantity };
  });
}

function reservationMatches(existing, items) {
  if (existing.length !== items.length) return false;
  const expected = new Map(items.map((item) => [`${item.productId}:${item.variantId}`, item.quantity]));
  return existing.every((row) => {
    const key = `${row.product_id}:${row.variant_id}`;
    return expected.get(key) === toInt(row.quantity);
  });
}

async function getInventory(req, res) {
  try {
    const productId = req.params.productId;
    const variantId = req.query.variantId != null ? normalizeVariantId(req.query.variantId) : null;
    const where = { product_id: productId };
    if (variantId != null) where.variant_id = variantId;

    const rows = await Inventory.findAll({ where, order: [['variant_id', 'ASC']] });
    if (!rows.length) {
      return res.status(404).json({ message: 'Inventory not found' });
    }
    const data = rows.map(toPublicInventory);
    return res.json(variantId != null ? data[0] : data);
  } catch (err) {
    return res.status(500).json({ message: 'Get inventory failed', error: err.message });
  }
}

async function updateInventory(req, res) {
  try {
    const productId = String(req.params.productId || '').trim();
    const variantId = normalizeVariantId(req.params.variantId ?? req.body.variantId);
    const stockOnHand = toInt(req.body.stockOnHand ?? req.body.stock ?? req.body.quantity, NaN);
    const hasReservedStock = req.body.reservedStock != null || req.body.reserved_stock != null;
    const reservedStock = hasReservedStock ? toInt(req.body.reservedStock ?? req.body.reserved_stock, NaN) : null;
    if (!productId || !Number.isFinite(stockOnHand) || stockOnHand < 0 || (hasReservedStock && (!Number.isFinite(reservedStock) || reservedStock < 0))) {
      return res.status(400).json({ message: 'invalid inventory data' });
    }

    const [record] = await Inventory.findOrCreate({
      where: { product_id: productId, variant_id: variantId },
      defaults: {
        product_id: productId,
        variant_id: variantId,
        shop_id: req.body.shopId || req.body.shop_id || null,
        sku: req.body.sku || null,
        stock_on_hand: stockOnHand,
        reserved_stock: reservedStock || 0
      }
    });

    record.shop_id = req.body.shopId ?? req.body.shop_id ?? record.shop_id;
    record.sku = req.body.sku ?? record.sku;
    if (hasReservedStock) record.reserved_stock = reservedStock;
    if (toInt(record.reserved_stock) > stockOnHand) {
      return res.status(400).json({ message: 'stockOnHand cannot be lower than reservedStock' });
    }
    record.stock_on_hand = stockOnHand;
    record.updated_at = new Date();
    await record.save();

    return res.json(toPublicInventory(record));
  } catch (err) {
    return res.status(500).json({ message: 'Update inventory failed', error: err.message });
  }
}

async function syncProductInventory(product, options = {}) {
  const syncStock = options.syncStock !== false;
  const productId = String(product?.id || product?._id || product?.productId || '').trim();
  if (!productId) return [];
  const shopId = product?.shopId || product?.shop_id || null;
  const variants = Array.isArray(product?.variants) ? product.variants : [];
  const rows = variants.length
    ? variants.map((variant) => ({
        productId,
        variantId: normalizeVariantId(variant?._id || variant?.id || variant?.variantId),
        shopId,
        sku: variant?.sku || null,
        stockOnHand: toInt(variant?.quantity, 0)
      }))
    : [{
        productId,
        variantId: '',
        shopId,
        sku: product?.sku || null,
        stockOnHand: toInt(product?.quantity, 0)
      }];

  const synced = [];
  await sequelize.transaction(async (transaction) => {
    for (const row of rows) {
      const [record, created] = await Inventory.findOrCreate({
        where: { product_id: row.productId, variant_id: row.variantId },
        defaults: {
          product_id: row.productId,
          variant_id: row.variantId,
          shop_id: row.shopId,
          sku: row.sku,
          stock_on_hand: row.stockOnHand,
          reserved_stock: 0
        },
        transaction,
        lock: transaction.LOCK.UPDATE
      });
      record.shop_id = row.shopId;
      record.sku = row.sku;
      if (created || syncStock) {
        record.stock_on_hand = Math.max(row.stockOnHand, toInt(record.reserved_stock));
      }
      record.updated_at = new Date();
      await record.save({ transaction });
      synced.push(toPublicInventory(record));
    }
  });
  return synced;
}

async function syncProduct(req, res) {
  try {
    const synced = await syncProductInventory(req.body || {});
    return res.json({ items: synced });
  } catch (err) {
    return res.status(500).json({ message: 'Sync product inventory failed', error: err.message });
  }
}

async function reserveInventory(req, res) {
  try {
    const orderId = String(req.body?.orderId || '').trim();
    if (!orderId) return res.status(400).json({ message: 'orderId is required' });
    const items = normalizeItems(req.body?.items);
    const reserved = [];

    await sequelize.transaction(async (transaction) => {
      const existing = await InventoryReservation.findAll({
        where: { order_id: orderId },
        transaction,
        lock: transaction.LOCK.UPDATE
      });
      if (existing.length) {
        if (!reservationMatches(existing, items)) {
          const err = new Error('orderId is already used with different inventory items');
          err.status = 409;
          throw err;
        }
        reserved.push(...existing);
        return;
      }

      for (const item of items) {
        const [results] = await sequelize.query(
          `UPDATE inventory
             SET reserved_stock = reserved_stock + :quantity,
                 updated_at = NOW()
           WHERE product_id = :productId
             AND variant_id = :variantId
             AND stock_on_hand - reserved_stock >= :quantity
           RETURNING *`,
          {
            replacements: item,
            transaction
          }
        );
        if (!results.length) {
          const err = new Error('Out of stock');
          err.status = 409;
          throw err;
        }
        const row = await InventoryReservation.create(
          {
            order_id: orderId,
            product_id: item.productId,
            variant_id: item.variantId,
            quantity: item.quantity,
            status: 'reserved'
          },
          { transaction }
        );
        reserved.push(row);
      }
    });

    return res.json({ orderId, status: 'reserved', reservations: reserved.map((row) => row.toJSON()) });
  } catch (err) {
    return res.status(err.status || 500).json({ message: err.message || 'Reserve inventory failed' });
  }
}

async function releaseInventory(req, res) {
  try {
    const orderId = String(req.body?.orderId || '').trim();
    if (!orderId) return res.status(400).json({ message: 'orderId is required' });
    const restoreCommitted = Boolean(req.body?.restoreCommitted);
    let releasedCount = 0;

    await sequelize.transaction(async (transaction) => {
      const statuses = restoreCommitted ? ['reserved', 'committed'] : ['reserved'];
      const reservations = await InventoryReservation.findAll({
        where: { order_id: orderId, status: statuses },
        transaction,
        lock: transaction.LOCK.UPDATE
      });
      for (const row of reservations) {
        const inventory = await Inventory.findOne({
          where: { product_id: row.product_id, variant_id: row.variant_id },
          transaction,
          lock: transaction.LOCK.UPDATE
        });
        if (inventory) {
          if (row.status === 'reserved') {
            inventory.reserved_stock = Math.max(0, toInt(inventory.reserved_stock) - toInt(row.quantity));
          } else if (row.status === 'committed' && restoreCommitted) {
            inventory.stock_on_hand = toInt(inventory.stock_on_hand) + toInt(row.quantity);
          }
          inventory.updated_at = new Date();
          await inventory.save({ transaction });
        }
        row.status = 'released';
        row.updated_at = new Date();
        await row.save({ transaction });
        releasedCount += 1;
      }
    });

    return res.json({ orderId, status: 'released', releasedCount });
  } catch (err) {
    return res.status(500).json({ message: 'Release inventory failed', error: err.message });
  }
}

async function commitInventory(req, res) {
  try {
    const orderId = String(req.body?.orderId || '').trim();
    if (!orderId) return res.status(400).json({ message: 'orderId is required' });
    let committedCount = 0;

    await sequelize.transaction(async (transaction) => {
      const reservations = await InventoryReservation.findAll({
        where: { order_id: orderId, status: 'reserved' },
        transaction,
        lock: transaction.LOCK.UPDATE
      });
      for (const row of reservations) {
        const inventory = await Inventory.findOne({
          where: { product_id: row.product_id, variant_id: row.variant_id },
          transaction,
          lock: transaction.LOCK.UPDATE
        });
        if (!inventory || toInt(inventory.reserved_stock) < toInt(row.quantity) || toInt(inventory.stock_on_hand) < toInt(row.quantity)) {
          const err = new Error('Reserved stock is inconsistent');
          err.status = 409;
          throw err;
        }
        inventory.stock_on_hand = toInt(inventory.stock_on_hand) - toInt(row.quantity);
        inventory.reserved_stock = toInt(inventory.reserved_stock) - toInt(row.quantity);
        inventory.updated_at = new Date();
        await inventory.save({ transaction });
        row.status = 'committed';
        row.updated_at = new Date();
        await row.save({ transaction });
        committedCount += 1;
      }
    });

    return res.json({ orderId, status: 'committed', committedCount });
  } catch (err) {
    return res.status(err.status || 500).json({ message: err.message || 'Commit inventory failed' });
  }
}

module.exports = {
  getInventory,
  updateInventory,
  syncProduct,
  syncProductInventory,
  reserveInventory,
  releaseInventory,
  commitInventory
};
