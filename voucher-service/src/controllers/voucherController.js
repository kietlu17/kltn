const { Op } = require('sequelize');
const { sequelize } = require('../config/db');
const Voucher = require('../models/Voucher');
const VoucherReservation = require('../models/VoucherReservation');

const VOUCHER_TYPES = new Set(['shop', 'platform']);
const DISCOUNT_TYPES = new Set(['percent']);
const VOUCHER_STATUSES = new Set(['active', 'inactive']);

function normalizeCode(value) {
  return String(value || '').trim().toUpperCase().slice(0, 40);
}

function toNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function toInt(value, defaultValue = 0) {
  const number = Number.parseInt(value, 10);
  return Number.isFinite(number) ? number : defaultValue;
}

function normalizeItems(items) {
  if (!Array.isArray(items)) return [];
  return items
    .map((item) => ({
      productId: item.productId || item.product_id || null,
      shopId: item.shopId || item.shop_id || null,
      quantity: Math.max(toInt(item.quantity, 0), 0),
      price: Math.max(toNumber(item.price), 0)
    }))
    .filter((item) => item.productId && item.shopId && item.quantity > 0);
}

function subtotal(items) {
  return items.reduce((sum, item) => sum + item.price * item.quantity, 0);
}

function applicableItems(voucher, items) {
  if (voucher.type === 'platform') return items;
  return items.filter((item) => String(item.shopId) === String(voucher.shop_id || ''));
}

function calculateDiscount(voucher, items) {
  const base = subtotal(applicableItems(voucher, items));
  if (base <= 0) return 0;
  let discount = 0;
  if (voucher.discount_type === 'percent') {
    discount = base * (toNumber(voucher.discount_value) / 100);
  }
  const maxDiscount = toNumber(voucher.max_discount_amount);
  if (maxDiscount > 0) discount = Math.min(discount, maxDiscount);
  return Math.max(0, Math.min(base, Math.floor(discount)));
}

function validateVoucherShape(payload, actorRole, actorShopId) {
  const code = normalizeCode(payload.code);
  const type = String(payload.type || '').toLowerCase();
  const discountType = String(payload.discountType || payload.discount_type || 'percent').toLowerCase();
  const discountValue = toNumber(payload.discountValue ?? payload.discount_value);
  const quantity = toInt(payload.quantity, 0);
  const minOrderAmount = toNumber(payload.minOrderAmount ?? payload.min_order_amount);
  const usageLimitPerUser = Math.max(toInt(payload.usageLimitPerUser ?? payload.usage_limit_per_user, 1), 1);
  const startAt = new Date(payload.startAt || payload.start_at);
  const endAt = new Date(payload.endAt || payload.end_at);
  let shopId = payload.shopId ?? payload.shop_id ?? null;

  if (!code) return { error: 'code is required' };
  if (!payload.name || !String(payload.name).trim()) return { error: 'name is required' };
  if (!VOUCHER_TYPES.has(type)) return { error: 'type must be shop or platform' };
  if (!DISCOUNT_TYPES.has(discountType)) return { error: 'discountType must be percent' };
  if (discountValue <= 0 || discountValue > 100) return { error: 'discountValue must be between 1 and 100' };
  if (quantity < 1) return { error: 'quantity must be at least 1' };
  if (!Number.isFinite(startAt.getTime()) || !Number.isFinite(endAt.getTime())) {
    return { error: 'startAt and endAt are required' };
  }
  if (startAt >= endAt) return { error: 'endAt must be after startAt' };
  if (type === 'shop') {
    shopId = shopId || actorShopId;
    if (!shopId) return { error: 'shopId is required for shop vouchers' };
  } else {
    shopId = null;
    if (actorRole !== 'admin') return { error: 'Only admin can create platform vouchers', status: 403 };
  }

  return {
    value: {
      code,
      name: String(payload.name).trim(),
      type,
      shop_id: shopId ? String(shopId) : null,
      discount_type: discountType,
      discount_value: discountValue,
      max_discount_amount: (payload.maxDiscountAmount ?? payload.max_discount_amount) || null,
      min_order_amount: Math.max(minOrderAmount, 0),
      quantity,
      usage_limit_per_user: usageLimitPerUser,
      start_at: startAt,
      end_at: endAt,
      status: VOUCHER_STATUSES.has(String(payload.status || '').toLowerCase())
        ? String(payload.status).toLowerCase()
        : 'active'
    }
  };
}

async function buildVoucherView(voucher, items, userId) {
  const now = new Date();
  const cartSubtotal = subtotal(applicableItems(voucher, items));
  const remaining = Math.max(toInt(voucher.quantity) - toInt(voucher.used_count), 0);
  let eligible = true;
  let reason = '';

  if (voucher.status !== 'active') {
    eligible = false;
    reason = 'Voucher is inactive';
  } else if (voucher.start_at > now) {
    eligible = false;
    reason = 'Voucher is not started';
  } else if (voucher.end_at < now) {
    eligible = false;
    reason = 'Voucher is expired';
  } else if (remaining <= 0) {
    eligible = false;
    reason = 'Voucher is out of uses';
  } else if (cartSubtotal <= 0) {
    eligible = false;
    reason = 'Voucher does not apply to this shop';
  } else if (cartSubtotal < toNumber(voucher.min_order_amount)) {
    eligible = false;
    reason = `Minimum order amount is ${voucher.min_order_amount}`;
  }

  if (eligible && userId) {
    const activeUserUses = await VoucherReservation.count({
      where: {
        voucher_id: voucher.id,
        user_id: String(userId),
        status: { [Op.in]: ['reserved', 'committed'] }
      }
    });
    if (activeUserUses >= toInt(voucher.usage_limit_per_user, 1)) {
      eligible = false;
      reason = 'User usage limit reached';
    }
  }

  const discountAmount = eligible ? calculateDiscount(voucher, items) : 0;
  return {
    id: voucher.id,
    code: voucher.code,
    name: voucher.name,
    type: voucher.type,
    shopId: voucher.shop_id,
    discountType: voucher.discount_type,
    discountValue: toNumber(voucher.discount_value),
    maxDiscountAmount: voucher.max_discount_amount == null ? null : toNumber(voucher.max_discount_amount),
    minOrderAmount: toNumber(voucher.min_order_amount),
    quantity: toInt(voucher.quantity),
    usedCount: toInt(voucher.used_count),
    remaining,
    usageLimitPerUser: toInt(voucher.usage_limit_per_user, 1),
    startAt: voucher.start_at,
    endAt: voucher.end_at,
    status: voucher.status,
    eligible,
    reason,
    discountAmount
  };
}

async function listVouchers(req, res) {
  try {
    const actorRole = req.headers['x-user-role'] || '';
    const actorShopId = req.headers['x-user-shop-id'] || '';
    const where = {};
    if (req.query.type) where.type = String(req.query.type).toLowerCase();
    if (actorRole === 'seller') {
      where.type = 'shop';
      where.shop_id = actorShopId || '__none__';
    } else if (req.query.shopId) {
      where.shop_id = String(req.query.shopId);
    }
    const rows = await Voucher.findAll({ where, order: [['created_at', 'DESC']] });
    return res.json(rows.map((row) => row.toJSON()));
  } catch (err) {
    return res.status(500).json({ message: 'List vouchers failed', error: err.message });
  }
}

async function listCheckoutVouchers(req, res) {
  try {
    const items = normalizeItems(req.body?.items);
    const userId = req.headers['x-user-id'] || req.body?.userId || '';
    if (!items.length) return res.status(400).json({ message: 'items are required' });
    const shopIds = [...new Set(items.map((item) => String(item.shopId)))];
    const rows = await Voucher.findAll({
      where: {
        [Op.or]: [
          { type: 'platform' },
          { type: 'shop', shop_id: { [Op.in]: shopIds } }
        ]
      }
    });
    const views = await Promise.all(rows.map((voucher) => buildVoucherView(voucher, items, userId)));
    views.sort((a, b) => {
      if (a.eligible !== b.eligible) return a.eligible ? -1 : 1;
      return b.discountAmount - a.discountAmount;
    });
    return res.json(views);
  } catch (err) {
    return res.status(500).json({ message: 'List checkout vouchers failed', error: err.message });
  }
}

async function createVoucher(req, res) {
  try {
    const actorRole = req.headers['x-user-role'] || '';
    const actorUserId = req.headers['x-user-id'] || '';
    const actorShopId = req.headers['x-user-shop-id'] || '';
    if (!['seller', 'admin'].includes(actorRole)) {
      return res.status(403).json({ message: 'Forbidden' });
    }
    const parsed = validateVoucherShape(req.body || {}, actorRole, actorShopId);
    if (parsed.error) return res.status(parsed.status || 400).json({ message: parsed.error });
    const voucher = await Voucher.create({
      ...parsed.value,
      created_by: actorUserId || null,
      created_by_role: actorRole || null
    });
    return res.status(201).json(voucher.toJSON());
  } catch (err) {
    if (err.name === 'SequelizeUniqueConstraintError') {
      return res.status(409).json({ message: 'Voucher code already exists' });
    }
    return res.status(500).json({ message: 'Create voucher failed', error: err.message });
  }
}

async function updateVoucher(req, res) {
  try {
    const actorRole = req.headers['x-user-role'] || '';
    const actorShopId = req.headers['x-user-shop-id'] || '';
    if (!['seller', 'admin'].includes(actorRole)) {
      return res.status(403).json({ message: 'Forbidden' });
    }
    const voucher = await Voucher.findByPk(Number(req.params.id));
    if (!voucher) return res.status(404).json({ message: 'Voucher not found' });
    if (actorRole === 'seller' && (voucher.type !== 'shop' || String(voucher.shop_id) !== String(actorShopId))) {
      return res.status(403).json({ message: 'Forbidden' });
    }
    const payload = { ...voucher.toJSON(), ...req.body };
    const parsed = validateVoucherShape(payload, actorRole, actorShopId);
    if (parsed.error) return res.status(parsed.status || 400).json({ message: parsed.error });
    if (toInt(parsed.value.quantity) < toInt(voucher.used_count)) {
      return res.status(400).json({ message: 'quantity cannot be lower than usedCount' });
    }
    await voucher.update({ ...parsed.value, updated_at: new Date() });
    return res.json(voucher.toJSON());
  } catch (err) {
    if (err.name === 'SequelizeUniqueConstraintError') {
      return res.status(409).json({ message: 'Voucher code already exists' });
    }
    return res.status(500).json({ message: 'Update voucher failed', error: err.message });
  }
}

async function reserveVoucher(req, res) {
  const transaction = await sequelize.transaction();
  try {
    const code = normalizeCode(req.body?.code);
    const orderId = Number(req.body?.orderId);
    const userId = req.body?.userId || '';
    const items = normalizeItems(req.body?.items);
    if (!code || !Number.isFinite(orderId) || !userId || !items.length) {
      await transaction.rollback();
      return res.status(400).json({ message: 'code, orderId, userId and items are required' });
    }

    const voucher = await Voucher.findOne({
      where: { code },
      lock: transaction.LOCK.UPDATE,
      transaction
    });
    if (!voucher) {
      await transaction.rollback();
      return res.status(404).json({ message: 'Voucher not found' });
    }

    const existing = await VoucherReservation.findOne({
      where: {
        voucher_id: voucher.id,
        order_id: orderId,
        status: { [Op.in]: ['reserved', 'committed'] }
      },
      transaction
    });
    if (existing) {
      await transaction.commit();
      return res.json({
        voucher: await buildVoucherView(voucher, items, userId),
        discountAmount: toNumber(existing.discount_amount),
        reservation: existing.toJSON()
      });
    }

    const view = await buildVoucherView(voucher, items, userId);
    if (!view.eligible || view.discountAmount <= 0) {
      await transaction.rollback();
      return res.status(409).json({ message: view.reason || 'Voucher is not eligible', voucher: view });
    }

    voucher.used_count = toInt(voucher.used_count) + 1;
    voucher.updated_at = new Date();
    await voucher.save({ transaction });
    const reservation = await VoucherReservation.create({
      voucher_id: voucher.id,
      order_id: orderId,
      user_id: String(userId),
      discount_amount: view.discountAmount,
      status: 'reserved'
    }, { transaction });

    await transaction.commit();
    return res.status(201).json({
      voucher: { ...view, usedCount: toInt(voucher.used_count), remaining: Math.max(toInt(voucher.quantity) - toInt(voucher.used_count), 0) },
      discountAmount: view.discountAmount,
      reservation: reservation.toJSON()
    });
  } catch (err) {
    await transaction.rollback();
    return res.status(500).json({ message: 'Reserve voucher failed', error: err.message });
  }
}

async function releaseVoucher(req, res) {
  const transaction = await sequelize.transaction();
  try {
    const orderId = Number(req.body?.orderId);
    if (!Number.isFinite(orderId)) {
      await transaction.rollback();
      return res.status(400).json({ message: 'orderId is required' });
    }
    const statuses = req.body?.restoreCommitted ? ['reserved', 'committed'] : ['reserved'];
    const reservations = await VoucherReservation.findAll({
      where: { order_id: orderId, status: { [Op.in]: statuses } },
      lock: transaction.LOCK.UPDATE,
      transaction
    });
    for (const reservation of reservations) {
      const voucher = await Voucher.findByPk(reservation.voucher_id, {
        lock: transaction.LOCK.UPDATE,
        transaction
      });
      if (voucher) {
        voucher.used_count = Math.max(toInt(voucher.used_count) - 1, 0);
        voucher.updated_at = new Date();
        await voucher.save({ transaction });
      }
      reservation.status = 'released';
      reservation.updated_at = new Date();
      await reservation.save({ transaction });
    }
    await transaction.commit();
    return res.json({ released: reservations.length });
  } catch (err) {
    await transaction.rollback();
    return res.status(500).json({ message: 'Release voucher failed', error: err.message });
  }
}

async function commitVoucher(req, res) {
  const transaction = await sequelize.transaction();
  try {
    const orderId = Number(req.body?.orderId);
    if (!Number.isFinite(orderId)) {
      await transaction.rollback();
      return res.status(400).json({ message: 'orderId is required' });
    }
    const reservations = await VoucherReservation.findAll({
      where: { order_id: orderId, status: 'reserved' },
      transaction
    });
    for (const reservation of reservations) {
      reservation.status = 'committed';
      reservation.updated_at = new Date();
      await reservation.save({ transaction });
    }
    await transaction.commit();
    return res.json({ committed: reservations.length });
  } catch (err) {
    await transaction.rollback();
    return res.status(500).json({ message: 'Commit voucher failed', error: err.message });
  }
}

module.exports = {
  listVouchers,
  listCheckoutVouchers,
  createVoucher,
  updateVoucher,
  reserveVoucher,
  releaseVoucher,
  commitVoucher
};
