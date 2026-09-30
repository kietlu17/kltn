const fs = require('fs');
const https = require('https');
const fetchImpl = require('node-fetch');
const Cart = require('../models/Cart');

const PRODUCT_SERVICE_URL = process.env.PRODUCT_SERVICE_URL || 'http://localhost:3004';
const INVENTORY_SERVICE_URL = process.env.INVENTORY_SERVICE_URL || 'http://localhost:3007';
const MAX_LINE_QUANTITY = Math.max(1, Number(process.env.CART_MAX_LINE_QUANTITY || 100));

function createMtlsAgent() {
  if (process.env.MTLS_ENABLED !== 'true') return null;
  return new https.Agent({
    ca: fs.readFileSync(process.env.MTLS_CA_PATH || process.env.TLS_CA_PATH),
    cert: fs.readFileSync(process.env.MTLS_CLIENT_CERT_PATH || process.env.TLS_CERT_PATH),
    key: fs.readFileSync(process.env.MTLS_CLIENT_KEY_PATH || process.env.TLS_KEY_PATH),
    rejectUnauthorized: process.env.MTLS_REJECT_UNAUTHORIZED !== 'false'
  });
}

const mtlsAgent = createMtlsAgent();

function requestOptions(url, options = {}) {
  return mtlsAgent && url.startsWith('https://') ? { ...options, agent: mtlsAgent } : options;
}

function isSameLine(item, productId, variantId) {
  return String(item.productId) === String(productId) && String(item.variantId || '') === String(variantId || '');
}

function requireBuyer(req, requestedUserId) {
  const actorId = String(req.headers['x-user-id'] || '').trim();
  const role = String(req.headers['x-user-role'] || '').trim();
  if (!actorId || !['buyer', 'admin'].includes(role)) {
    const error = new Error('Authenticated buyer is required');
    error.status = 401;
    throw error;
  }
  const userId = role === 'admin' && requestedUserId ? String(requestedUserId) : actorId;
  if (role === 'buyer' && requestedUserId && String(requestedUserId) !== actorId) {
    const error = new Error('Forbidden');
    error.status = 403;
    throw error;
  }
  return userId;
}

function parseQuantity(value, { allowZero = false } = {}) {
  const quantity = Number(value);
  const minimum = allowZero ? 0 : 1;
  if (!Number.isSafeInteger(quantity) || quantity < minimum || quantity > MAX_LINE_QUANTITY) {
    const error = new Error(`quantity must be an integer from ${minimum} to ${MAX_LINE_QUANTITY}`);
    error.status = 400;
    throw error;
  }
  return quantity;
}

async function fetchJson(url) {
  const response = await fetchImpl(url, requestOptions(url));
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const error = new Error(payload?.message || `Dependency request failed with status ${response.status}`);
    error.status = response.status === 404 ? 404 : 502;
    throw error;
  }
  return payload;
}

async function validateCartLine(productId, variantId, quantity) {
  if (!/^[a-fA-F0-9]{24}$/.test(String(productId || ''))) {
    const error = new Error('Invalid productId');
    error.status = 400;
    throw error;
  }
  const normalizedVariantId = String(variantId || '');
  const productUrl = `${PRODUCT_SERVICE_URL}/products/${encodeURIComponent(productId)}`;
  const inventoryUrl = `${INVENTORY_SERVICE_URL}/inventory/products/${encodeURIComponent(productId)}`;
  const [product, inventory] = await Promise.all([fetchJson(productUrl), fetchJson(inventoryUrl)]);
  if (product.moderationStatus !== 'approved') {
    const error = new Error('Product is not available');
    error.status = 409;
    throw error;
  }
  const variants = Array.isArray(product.variants) ? product.variants : [];
  if (variants.length > 0 && !normalizedVariantId) {
    const error = new Error('variantId is required for this product');
    error.status = 400;
    throw error;
  }
  if (variants.length > 0 && !variants.some((item) => String(item._id) === normalizedVariantId)) {
    const error = new Error('Variant is not available');
    error.status = 409;
    throw error;
  }
  if (variants.length === 0 && normalizedVariantId) {
    const error = new Error('This product has no variants');
    error.status = 400;
    throw error;
  }
  const rows = Array.isArray(inventory) ? inventory : [inventory];
  const stock = rows.find((item) => String(item?.variantId || '') === normalizedVariantId);
  if (!stock || Number(stock.availableStock || 0) < quantity) {
    const error = new Error('Out of stock');
    error.status = 409;
    throw error;
  }
}

function sendError(res, err, fallback) {
  const status = Number(err?.status);
  return res.status(Number.isInteger(status) && status >= 400 && status < 600 ? status : 500)
    .json({ message: status ? err.message : fallback, ...(status ? {} : { error: err.message }) });
}

async function addToCart(req, res) {
  try {
    const { productId, variantId } = req.body || {};
    const userId = requireBuyer(req, req.body?.userId);
    const quantity = parseQuantity(req.body?.quantity);
    const actionKey = String(req.body?.actionKey || '').trim().slice(0, 128);
    if (!productId) return res.status(400).json({ message: 'productId is required' });
    let cart = await Cart.findOne({ userId });
    const replay = actionKey && cart?.processedActions?.find((item) => item.key === actionKey);
    if (replay) {
      if (!isSameLine(replay, productId, variantId) || Number(replay.quantity) !== quantity) {
        return res.status(409).json({ message: 'actionKey is already used with a different cart action' });
      }
      return res.json({ cart, changed: false, replayed: true });
    }
    const existing = cart?.products.find((item) => isSameLine(item, productId, variantId));
    const targetQuantity = Number(existing?.quantity || 0) + quantity;
    parseQuantity(targetQuantity);
    await validateCartLine(productId, variantId, targetQuantity);
    if (!cart) {
      cart = await Cart.create({
        userId,
        products: [{ productId, variantId: variantId || null, quantity }],
        processedActions: actionKey ? [{ key: actionKey, productId, variantId: variantId || null, quantity }] : []
      });
      return res.status(201).json({ cart, changed: true, replayed: false });
    }
    if (existing) existing.quantity = targetQuantity;
    else cart.products.push({ productId, variantId: variantId || null, quantity });
    if (actionKey) {
      cart.processedActions.push({ key: actionKey, productId, variantId: variantId || null, quantity });
      if (cart.processedActions.length > 100) cart.processedActions.splice(0, cart.processedActions.length - 100);
    }
    await cart.save();
    return res.json({ cart, changed: true, replayed: false });
  } catch (err) {
    return sendError(res, err, 'Add to cart failed');
  }
}

async function upsertCartLine(req, res) {
  try {
    const { productId, variantId } = req.body || {};
    const userId = requireBuyer(req, req.body?.userId);
    const targetQuantity = parseQuantity(req.body?.targetQuantity, { allowZero: true });
    if (!productId) return res.status(400).json({ message: 'productId is required' });
    let cart = await Cart.findOne({ userId });
    const existing = cart?.products.find((item) => isSameLine(item, productId, variantId));
    const currentQuantity = Number(existing?.quantity || 0);
    if (req.body?.expectedCurrentQuantity != null && Number(req.body.expectedCurrentQuantity) !== currentQuantity) {
      return res.status(409).json({ message: 'Cart changed; refresh before retrying', currentQuantity });
    }
    if (targetQuantity > 0) await validateCartLine(productId, variantId, targetQuantity);
    if (!cart) cart = await Cart.create({ userId, products: [] });
    if (targetQuantity === 0) {
      cart.products = cart.products.filter((item) => !isSameLine(item, productId, variantId));
    } else if (existing) {
      existing.quantity = targetQuantity;
    } else {
      cart.products.push({ productId, variantId: variantId || null, quantity: targetQuantity });
    }
    await cart.save();
    return res.json({ cart, changed: currentQuantity !== targetQuantity, previousQuantity: currentQuantity });
  } catch (err) {
    return sendError(res, err, 'Update cart failed');
  }
}

async function removeFromCart(req, res) {
  try {
    const { productId, variantId } = req.body || {};
    const userId = requireBuyer(req, req.body?.userId);
    if (!productId) return res.status(400).json({ message: 'productId is required' });
    const cart = await Cart.findOne({ userId });
    if (!cart) return res.status(404).json({ message: 'Cart not found' });
    cart.products = cart.products.filter((item) => !isSameLine(item, productId, variantId));
    await cart.save();
    return res.json(cart);
  } catch (err) {
    return sendError(res, err, 'Remove from cart failed');
  }
}

async function updateQuantity(req, res) {
  try {
    const { productId, variantId } = req.body || {};
    const userId = requireBuyer(req, req.body?.userId);
    const quantity = parseQuantity(req.body?.quantity);
    if (!productId) return res.status(400).json({ message: 'productId is required' });
    const cart = await Cart.findOne({ userId });
    if (!cart) return res.status(404).json({ message: 'Cart not found' });
    const item = cart.products.find((line) => isSameLine(line, productId, variantId));
    if (!item) return res.status(404).json({ message: 'Product not in cart' });
    await validateCartLine(productId, variantId, quantity);
    item.quantity = quantity;
    await cart.save();
    return res.json(cart);
  } catch (err) {
    return sendError(res, err, 'Update cart failed');
  }
}

async function getCart(req, res) {
  try {
    const userId = requireBuyer(req, req.params.userId);
    const cart = await Cart.findOne({ userId });
    return res.json(cart || { userId, products: [] });
  } catch (err) {
    return sendError(res, err, 'Get cart failed');
  }
}

module.exports = { addToCart, upsertCartLine, removeFromCart, updateQuantity, getCart };
