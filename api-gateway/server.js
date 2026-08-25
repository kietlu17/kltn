require('dotenv').config();
const express = require('express');
const cors = require('cors');
const morgan = require('morgan');
const jwt = require('jsonwebtoken');
const fs = require('fs');
const https = require('https');
const { createProxyMiddleware, fixRequestBody } = require('http-proxy-middleware');
const fetchImpl = require('node-fetch');

const app = express();
const corsOptions = {
  origin: true,
  credentials: true,
  methods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization', 'X-Requested-With'],
  exposedHeaders: ['Content-Length']
};

app.use(cors(corsOptions));
app.options('*', cors(corsOptions));
app.use(express.json());
app.use(morgan('dev'));

const RATE_LIMIT_WINDOW_MS = Number(process.env.RATE_LIMIT_WINDOW_MS || 60 * 1000);
const RATE_LIMIT_MAX_REQUESTS = Number(process.env.RATE_LIMIT_MAX_REQUESTS || 120);
const AUTH_RATE_LIMIT_WINDOW_MS = Number(process.env.AUTH_RATE_LIMIT_WINDOW_MS || 60 * 1000);
const AUTH_RATE_LIMIT_MAX_REQUESTS = Number(process.env.AUTH_RATE_LIMIT_MAX_REQUESTS || 30);
const rateStore = new Map();

const targets = {
  auth: process.env.AUTH_SERVICE_URL || 'http://localhost:3001',
  users: process.env.USER_SERVICE_URL || 'http://localhost:3002',
  shops: process.env.SHOP_SERVICE_URL || 'http://localhost:3003',
  products: process.env.PRODUCT_SERVICE_URL || 'http://localhost:3004',
  inventory: process.env.INVENTORY_SERVICE_URL || 'http://localhost:3007',
  vouchers: process.env.VOUCHER_SERVICE_URL || 'http://localhost:3013',
  cart: process.env.CART_SERVICE_URL || 'http://localhost:3005',
  orders: process.env.ORDER_SERVICE_URL || 'http://localhost:3006',
  payments: process.env.PAYMENT_SERVICE_URL || 'http://localhost:3010',
  wallet: process.env.WALLET_SERVICE_URL || 'http://localhost:3011',
  paymentGateway: process.env.PAYMENT_GATEWAY_URL || 'http://localhost:3012',
  reviews: process.env.REVIEW_SERVICE_URL || 'http://localhost:3008',
  chat: process.env.CHAT_SERVICE_URL || 'http://localhost:3009',
  lives: process.env.LIVESTREAM_SERVICE_URL || 'http://localhost:3014'
};

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

function buildProxy(target) {
  const config = {
    target,
    changeOrigin: true,
    ws: true,
    logLevel: 'warn',
    onProxyReq: fixRequestBody
  };
  if (target.startsWith('https://')) {
    config.secure = process.env.MTLS_REJECT_UNAUTHORIZED !== 'false';
    if (mtlsAgent) config.agent = mtlsAgent;
  }
  return createProxyMiddleware(config);
}

const PUBLIC_PATHS = [
  { method: 'POST', path: '/auth/login' },
  { method: 'POST', path: '/auth/register' },
  { method: 'POST', path: '/auth/session' },
  { method: 'GET', path: '/shops' },
  { method: 'POST', path: '/lives/provider/livekit/webhook' },
  { method: 'POST', path: '/orders/shipping/callback' },
  { method: 'POST', path: '/payments/wallet/cod-remittances' },
  { method: 'POST', path: '/payments/sepay/webhook' }
];

function matchesPath(targetPath, reqPath) {
  return reqPath === targetPath || reqPath.startsWith(`${targetPath}/`);
}

function isPublicRequest(req) {
  if (req.path.startsWith('/shops/admin/') || /^\/shops\/[^/]+\/invoice-feature/.test(req.path)) {
    return false;
  }
  return PUBLIC_PATHS.some((item) => item.method === req.method && matchesPath(item.path, req.path));
}

function cleanupRateStore(now) {
  for (const [key, value] of rateStore.entries()) {
    if (value.expiresAt <= now) rateStore.delete(key);
  }
}

function rateLimitMiddleware(req, res, next) {
  const now = Date.now();
  if (rateStore.size > 10000) cleanupRateStore(now);

  const isAuthPath = req.path.startsWith('/auth/login') || req.path.startsWith('/auth/register');
  const windowMs = isAuthPath ? AUTH_RATE_LIMIT_WINDOW_MS : RATE_LIMIT_WINDOW_MS;
  const maxRequests = isAuthPath ? AUTH_RATE_LIMIT_MAX_REQUESTS : RATE_LIMIT_MAX_REQUESTS;

  const key = `${req.ip}:${isAuthPath ? 'auth' : 'default'}`;
  const current = rateStore.get(key);
  if (!current || current.expiresAt <= now) {
    rateStore.set(key, { count: 1, expiresAt: now + windowMs });
    return next();
  }
  if (current.count >= maxRequests) {
    return res.status(429).json({ message: 'Too many requests. Please try again later.' });
  }
  current.count += 1;
  return next();
}

function verifyJwtToken(token) {
  return jwt.verify(token, process.env.JWT_SECRET || 'devsecret');
}

function getRequiredRoles(req) {
  const path = req.path;
  const method = req.method;

  if (path.startsWith('/auth/admin/')) return ['admin'];
  if (path.startsWith('/orders/admin/')) return ['admin'];
  if (path.startsWith('/products/admin/')) return ['admin'];
  if (path.startsWith('/inventory')) {
    if (method === 'GET') return null;
    return ['seller', 'admin'];
  }
  if (path.startsWith('/vouchers')) {
    if (method === 'POST' && path === '/vouchers/checkout') return ['buyer', 'admin'];
    if (method === 'POST' && /^\/vouchers\/(reserve|release|commit)$/.test(path)) return ['admin'];
    if (method === 'GET') return ['seller', 'admin'];
    if (method === 'POST' && path === '/vouchers') return ['seller', 'admin'];
    if (method === 'PUT') return ['seller', 'admin'];
    return ['buyer', 'seller', 'admin'];
  }
  if (path.startsWith('/categories/admin/')) return ['admin'];
  if (path.startsWith('/users/admin/')) return ['admin'];

  if (path.startsWith('/seller/')) return ['seller', 'admin'];

  if (path.startsWith('/users')) return ['buyer', 'seller', 'admin'];
  if (path.startsWith('/shops/admin/')) return ['admin'];
  if (/^\/shops\/[^/]+\/invoice-feature/.test(path)) return ['seller', 'admin'];
  if (path.startsWith('/cart')) return ['buyer', 'admin'];
  if (path.startsWith('/chat')) return ['buyer', 'seller', 'admin'];
  if (path.startsWith('/lives')) {
    if (path.startsWith('/lives/provider/')) return null;
    if (method === 'GET') {
      if (path === '/lives/seller/me') return ['seller', 'admin'];
      return null;
    }
    if (path.endsWith('/viewer-token')) return ['buyer', 'admin'];
    return ['seller', 'admin'];
  }
  if (path.startsWith('/reviews')) return ['buyer', 'admin'];
  if (path.startsWith('/payments/wallet/platform-wallet')) return ['admin'];
  if (path.startsWith('/payments/wallet/cod-remittances')) return ['admin'];
  if (method === 'POST' && /^\/payments\/wallet\/shop\/[^/]+\/settlements$/.test(path)) return ['admin'];
  if (path.startsWith('/payments/wallet/settlements')) return ['admin'];
  if (path.startsWith('/payments/wallet/user-withdrawals/')) return ['admin'];
  if (path.startsWith('/payments/wallet/shop/')) return ['seller', 'admin'];
  if (path.startsWith('/payments/wallet/payouts/')) return ['admin'];
  if (path.startsWith('/payments/wallet')) return ['buyer', 'admin'];
  if (path.startsWith('/payments/sepay')) return ['buyer', 'admin'];

  if (path.startsWith('/orders')) {
    if (method === 'POST' && /^\/orders\/\d+\/confirm$/.test(path)) return ['seller', 'admin'];
    if (method === 'POST' && /^\/orders\/\d+\/shipments$/.test(path)) return ['seller', 'admin'];
    if (method === 'PATCH' && /^\/orders\/\d+\/invoice$/.test(path)) return ['seller', 'admin'];
    if (method === 'GET' && /^\/orders\/shipments\/order\/\d+$/.test(path)) return ['buyer', 'seller', 'admin'];
    if (method === 'POST' && /^\/orders\/shipments\/[^/]+\/simulate$/.test(path)) return ['admin'];
    if (method === 'POST' && path === '/orders/shipping/callback') return ['admin'];
    if (method === 'GET' && /^\/orders\/seller\//.test(path)) return ['seller', 'admin'];
    if (method === 'POST' && /^\/orders\/\d+\/cancel$/.test(path)) return ['buyer', 'admin'];
    if (method === 'POST' && /^\/orders\/\d+\/disputes$/.test(path)) return ['buyer', 'admin'];
    if (method === 'POST' && path === '/orders') return ['buyer', 'admin'];
    if (method === 'GET') return ['buyer', 'admin'];
    return ['buyer', 'seller', 'admin'];
  }

  if (path.startsWith('/products') || path.startsWith('/categories')) {
    if (method === 'GET') return null;
    return ['seller', 'admin'];
  }

  return null;
}

async function validateAuthToken(token) {
  const requestOptions = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token })
  };
  if (mtlsAgent && targets.auth.startsWith('https://')) {
    requestOptions.agent = mtlsAgent;
  }
  const response = await fetchImpl(`${targets.auth}/auth/session`, requestOptions);
  if (!response.ok) return null;
  const payload = await response.json();
  return payload?.user || null;
}

app.use(rateLimitMiddleware);

app.use(async (req, res, next) => {
  if (isPublicRequest(req)) return next();
  const requiredRoles = getRequiredRoles(req);
  const authHeader = req.headers.authorization || '';
  const token = authHeader.startsWith('Bearer ') ? authHeader.slice(7) : '';
  if (!requiredRoles) {
    if (!token) return next();
    try {
      const decoded = verifyJwtToken(token);
      const user = await validateAuthToken(token);
      if (user) {
        if (decoded.role !== user.role) {
          return res.status(401).json({ message: 'Invalid token role' });
        }
        req.headers['x-user-id'] = user.id;
        req.headers['x-user-role'] = user.role;
        req.headers['x-user-shop-id'] = user.shopId || '';
      }
    } catch (err) {
      return res.status(401).json({ message: 'Invalid or expired token' });
    }
    return next();
  }
  if (!token) {
    return res.status(401).json({ message: 'Unauthorized' });
  }
  try {
    const decoded = verifyJwtToken(token);
    const user = await validateAuthToken(token);
    if (!user) {
      return res.status(401).json({ message: 'Unauthorized' });
    }
    if (decoded.role !== user.role) {
      return res.status(401).json({ message: 'Invalid token role' });
    }
    if (!requiredRoles.includes(user.role)) {
      return res.status(403).json({ message: 'Forbidden' });
    }

    if (req.method === 'GET' && /^\/orders\/[^/]+$/.test(req.path) && user.role === 'buyer') {
      const targetUserId = req.path.split('/')[2];
      if (targetUserId !== 'user' && targetUserId !== user.id) {
        return res.status(403).json({ message: 'Forbidden' });
      }
    }
    if (/^\/payments\/wallet\/[^/]+/.test(req.path) && user.role === 'buyer') {
      const targetUserId = req.path.split('/')[3];
      if (targetUserId !== user.id) {
        return res.status(403).json({ message: 'Forbidden' });
      }
    }
    if (/^\/payments\/wallet\/shop\/[^/]+/.test(req.path) && user.role === 'seller') {
      const targetShopId = req.path.split('/')[4];
      if (String(targetShopId) !== String(user.shopId || '')) {
        return res.status(403).json({ message: 'Forbidden' });
      }
    }
    if (req.method === 'POST' && /^\/orders\/\d+\/disputes$/.test(req.path) && user.role === 'buyer') {
      req.headers['x-user-id'] = user.id;
    }

    req.headers['x-user-id'] = user.id;
    req.headers['x-user-role'] = user.role;
    req.headers['x-user-shop-id'] = user.shopId || '';
    return next();
  } catch (err) {
    return res.status(500).json({ message: 'Auth validation failed', error: err.message });
  }
});

app.use('/auth', buildProxy(targets.auth));
app.use('/users', buildProxy(targets.users));
app.use('/shops', buildProxy(targets.shops));
app.use('/products', buildProxy(targets.products));
app.use('/inventory', buildProxy(targets.inventory));
app.use('/vouchers', buildProxy(targets.vouchers));
app.use('/uploads', buildProxy(targets.products));
app.use('/categories', buildProxy(targets.products));
app.use('/cart', buildProxy(targets.cart));
app.use('/orders', buildProxy(targets.orders));
app.use('/payments/wallet/:userId/topup/sepay-qr', buildProxy(targets.paymentGateway));
app.use('/payments/wallet', buildProxy(targets.wallet));
app.use('/payments/sepay', buildProxy(targets.paymentGateway));
app.use('/payments', buildProxy(targets.payments));
app.use('/reviews', buildProxy(targets.reviews));
app.use('/chat', buildProxy(targets.chat));
app.use('/lives', buildProxy(targets.lives));

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`API Gateway running on port ${PORT}`);
});
