const fs = require('fs');
const https = require('https');
const fetchImpl = require('node-fetch');

const PRODUCT_SERVICE_URL = process.env.PRODUCT_SERVICE_URL || 'http://localhost:3004';
const INVENTORY_SERVICE_URL = process.env.INVENTORY_SERVICE_URL || 'http://localhost:3007';
const USER_SERVICE_URL = process.env.USER_SERVICE_URL || 'http://localhost:3002';
const MAX_ITEMS = 50;
const MAX_LINE_QUANTITY = 100;

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

function withAgent(url, options = {}) {
  return mtlsAgent && url.startsWith('https://') ? { ...options, agent: mtlsAgent } : options;
}

async function requestJson(url, options = {}) {
  const response = await fetchImpl(url, withAgent(url, options));
  const text = await response.text();
  let payload;
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

function normalizeRequestedItems(items) {
  if (!Array.isArray(items) || items.length === 0 || items.length > MAX_ITEMS) {
    const error = new Error(`products must contain 1 to ${MAX_ITEMS} items`);
    error.status = 400;
    throw error;
  }
  const merged = new Map();
  for (const item of items) {
    const productId = String(item?.productId || '').trim();
    const variantId = String(item?.variantId || '').trim();
    const quantity = Number(item?.quantity);
    if (!/^[a-fA-F0-9]{24}$/.test(productId) || !Number.isSafeInteger(quantity) || quantity <= 0) {
      const error = new Error('Each item requires a valid productId and positive integer quantity');
      error.status = 400;
      throw error;
    }
    const key = `${productId}:${variantId}`;
    const nextQuantity = (merged.get(key)?.quantity || 0) + quantity;
    if (nextQuantity > MAX_LINE_QUANTITY) {
      const error = new Error(`A cart line cannot exceed ${MAX_LINE_QUANTITY} units`);
      error.status = 400;
      throw error;
    }
    merged.set(key, { productId, variantId: variantId || null, quantity: nextQuantity });
  }
  return [...merged.values()];
}

async function canonicalizeProducts(items, { singleShop = true } = {}) {
  const requested = normalizeRequestedItems(items);
  const ids = [...new Set(requested.map((item) => item.productId))];
  const query = encodeURIComponent(ids.join(','));
  const [products, inventoryPayload] = await Promise.all([
    requestJson(`${PRODUCT_SERVICE_URL}/products/batch?ids=${query}`),
    requestJson(`${INVENTORY_SERVICE_URL}/inventory/products?ids=${query}`)
  ]);
  const productById = new Map((Array.isArray(products) ? products : []).map((item) => [String(item._id), item]));
  const stockByLine = new Map((inventoryPayload?.items || []).map((item) => [
    `${item.productId}:${String(item.variantId || '')}`, Number(item.availableStock || 0)
  ]));
  const canonical = requested.map((request) => {
    const product = productById.get(request.productId);
    if (!product || product.moderationStatus !== 'approved') {
      const error = new Error('A product is unavailable');
      error.status = 409;
      throw error;
    }
    const variants = Array.isArray(product.variants) ? product.variants : [];
    const variant = request.variantId
      ? variants.find((item) => String(item._id) === String(request.variantId))
      : null;
    if ((variants.length > 0 && !variant) || (variants.length === 0 && request.variantId)) {
      const error = new Error('A selected variant is unavailable');
      error.status = 409;
      throw error;
    }
    const lineKey = `${request.productId}:${String(request.variantId || '')}`;
    if ((stockByLine.get(lineKey) || 0) < request.quantity) {
      const error = new Error('Out of stock');
      error.status = 409;
      throw error;
    }
    const price = Number(variant?.price ?? product.price);
    if (!Number.isFinite(price) || price < 0 || !product.shopId) {
      const error = new Error('Product pricing is invalid');
      error.status = 409;
      throw error;
    }
    return {
      productId: request.productId,
      variantId: request.variantId,
      quantity: request.quantity,
      price,
      productName: String(product.name || '').slice(0, 300),
      variantName: variant ? String(variant.name || '').slice(0, 160) : '',
      image: String(variant?.imageUrl || product.images?.[0] || '').slice(0, 1000),
      shopId: String(product.shopId)
    };
  });
  const shopIds = new Set(canonical.map((item) => item.shopId));
  if (singleShop && shopIds.size > 1) {
    const error = new Error('Automatic checkout currently supports one shop per confirmation');
    error.status = 409;
    error.code = 'MULTI_SHOP_CONFIRMATION_REQUIRED';
    throw error;
  }
  return canonical;
}

async function ownedAddress(userId, addressId) {
  if (!addressId) {
    const error = new Error('addressId is required');
    error.status = 400;
    throw error;
  }
  const addresses = await requestJson(
    `${USER_SERVICE_URL}/users/${encodeURIComponent(userId)}/addresses`
  );
  const address = (Array.isArray(addresses) ? addresses : []).find(
    (item) => String(item._id || item.id) === String(addressId)
  );
  if (!address) {
    const error = new Error('Shipping address does not belong to this buyer');
    error.status = 403;
    throw error;
  }
  return {
    id: String(address._id || address.id),
    label: String(address.label || ''),
    fullName: String(address.fullName || ''),
    phone: String(address.phone || ''),
    line1: String(address.line1 || ''),
    line2: String(address.line2 || ''),
    city: String(address.city || ''),
    state: String(address.state || ''),
    postalCode: String(address.postalCode || ''),
    country: String(address.country || '')
  };
}

module.exports = { canonicalizeProducts, ownedAddress, requestJson, withAgent };
