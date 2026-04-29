const fs = require('fs');
const https = require('https');
const fetchImpl = require('node-fetch');
const Review = require('../models/Review');

const ORDER_SERVICE_URL = process.env.ORDER_SERVICE_URL || 'http://localhost:3006';
const PRODUCT_SERVICE_URL = process.env.PRODUCT_SERVICE_URL || 'http://localhost:3004';

function createMtlsAgent() {
  if (process.env.MTLS_ENABLED !== 'true') return null;
  const caPath = process.env.MTLS_CA_PATH || process.env.TLS_CA_PATH;
  const certPath = process.env.MTLS_CLIENT_CERT_PATH || process.env.TLS_CERT_PATH;
  const keyPath = process.env.MTLS_CLIENT_KEY_PATH || process.env.TLS_KEY_PATH;
  if (!caPath || !certPath || !keyPath) {
    throw new Error('MTLS is enabled but MTLS_CA_PATH / MTLS_CLIENT_CERT_PATH / MTLS_CLIENT_KEY_PATH is missing');
  }
  return new https.Agent({
    ca: fs.readFileSync(caPath),
    cert: fs.readFileSync(certPath),
    key: fs.readFileSync(keyPath),
    rejectUnauthorized: process.env.MTLS_REJECT_UNAUTHORIZED !== 'false'
  });
}

const mtlsAgent = createMtlsAgent();

function buildRequestOptions(url, options) {
  if (mtlsAgent && url.startsWith('https://')) {
    return { ...options, agent: mtlsAgent };
  }
  return options;
}

function normalizeProducts(rawProducts) {
  if (!rawProducts) return [];
  if (Array.isArray(rawProducts)) return rawProducts;
  try {
    const parsed = JSON.parse(rawProducts);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

async function hasPurchasedProduct(userId, productId) {
  const url = `${ORDER_SERVICE_URL}/orders/${userId}`;
  const response = await fetchImpl(url, buildRequestOptions(url, {}));
  if (!response.ok) {
    throw new Error(`Order lookup failed with status ${response.status}`);
  }
  const orders = await response.json();
  if (!Array.isArray(orders)) return false;
  return orders.some((order) => {
    if (order.status === 'cancelled') return false;
    const items = normalizeProducts(order.products);
    return items.some((item) => String(item.productId) === String(productId));
  });
}

async function ensureProductExists(productId) {
  const url = `${PRODUCT_SERVICE_URL}/products/${productId}`;
  const response = await fetchImpl(url, buildRequestOptions(url, {}));
  if (response.status === 404) {
    return false;
  }
  if (!response.ok) {
    throw new Error(`Product lookup failed with status ${response.status}`);
  }
  return true;
}

async function getReviewsByProduct(req, res) {
  try {
    const reviews = await Review.find({ productId: req.params.productId }).sort({ createdAt: -1 });
    return res.json(reviews);
  } catch (err) {
    return res.status(500).json({ message: 'Get reviews failed', error: err.message });
  }
}

async function createReview(req, res) {
  try {
    const { userId, userName, rating, comment } = req.body;
    const productId = req.params.productId;
    if (!userId || rating == null) {
      return res.status(400).json({ message: 'userId and rating are required' });
    }
    const numericRating = Number(rating);
    if (Number.isNaN(numericRating) || numericRating < 1 || numericRating > 5) {
      return res.status(400).json({ message: 'rating must be between 1 and 5' });
    }
    const productExists = await ensureProductExists(productId);
    if (!productExists) {
      return res.status(404).json({ message: 'Product not found' });
    }
    const existing = await Review.findOne({ productId, userId });
    if (existing) {
      return res.status(409).json({ message: 'Review already submitted' });
    }
    const purchased = await hasPurchasedProduct(userId, productId);
    if (!purchased) {
      return res.status(403).json({ message: 'You can only review products you purchased' });
    }
    const review = await Review.create({
      productId,
      userId,
      userName: userName || 'Anonymous',
      rating: numericRating,
      comment
    });
    return res.status(201).json(review);
  } catch (err) {
    return res.status(500).json({ message: 'Create review failed', error: err.message });
  }
}

module.exports = { getReviewsByProduct, createReview };
