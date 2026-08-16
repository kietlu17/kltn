const Product = require('../models/Product');
const ProductSalesEvent = require('../models/ProductSalesEvent');

function parseOrderItems(order) {
  if (Array.isArray(order?.products)) return order.products;
  if (typeof order?.products === 'string') {
    try {
      return JSON.parse(order.products);
    } catch {
      return [];
    }
  }
  return [];
}

function normalizeDeliveredOrder(order) {
  const orderId = order?.id || order?.orderId;
  const status = String(order?.status || '').toLowerCase();
  if (!orderId || status !== 'delivered') return null;

  const byProduct = new Map();
  parseOrderItems(order).forEach((item) => {
    const productId = item?.productId || item?.id;
    const quantity = Number(item?.quantity || 0);
    if (!productId || !Number.isFinite(quantity) || quantity <= 0) return;
    const key = String(productId);
    byProduct.set(key, (byProduct.get(key) || 0) + quantity);
  });

  const items = [...byProduct.entries()].map(([productId, quantity]) => ({ productId, quantity }));
  if (!items.length) return null;
  return { orderId: String(orderId), items };
}

async function incrementSoldQuantities(items) {
  const operations = items.map(({ productId, quantity }) =>
    Product.updateOne(
      { _id: productId },
      { $inc: { sold: quantity } }
    )
  );
  await Promise.all(operations);
}

async function applyDeliveredOrderSales(order) {
  const normalized = normalizeDeliveredOrder(order);
  if (!normalized) return { skipped: true, reason: 'not_delivered_or_empty' };

  const existing = await ProductSalesEvent.findOne({ orderId: normalized.orderId });
  if (existing?.status === 'processed') {
    return { skipped: true, reason: 'already_processed' };
  }

  let event = existing;
  if (!event) {
    try {
      event = await ProductSalesEvent.create({
        orderId: normalized.orderId,
        status: 'processing',
        itemCount: normalized.items.length,
        totalQuantity: normalized.items.reduce((sum, item) => sum + item.quantity, 0),
        payload: order
      });
    } catch (err) {
      if (err?.code === 11000) {
        return applyDeliveredOrderSales(order);
      }
      throw err;
    }
  } else {
    event.status = 'processing';
    event.lastError = '';
    event.itemCount = normalized.items.length;
    event.totalQuantity = normalized.items.reduce((sum, item) => sum + item.quantity, 0);
    event.payload = order;
    await event.save();
  }

  try {
    await incrementSoldQuantities(normalized.items);
    event.status = 'processed';
    event.processedAt = new Date();
    event.lastError = '';
    await event.save();
    return { processed: true, orderId: normalized.orderId, items: normalized.items };
  } catch (err) {
    event.status = 'failed';
    event.lastError = err.message || 'Apply delivered order sales failed';
    await event.save();
    throw err;
  }
}

module.exports = {
  applyDeliveredOrderSales,
  normalizeDeliveredOrder
};
