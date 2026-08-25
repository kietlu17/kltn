const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const fs = require('fs');
const https = require('https');
const User = require('../models/User');

const fetchImpl = require('node-fetch');

const USER_SERVICE_URL = process.env.USER_SERVICE_URL || 'http://localhost:3002';
const SHOP_SERVICE_URL = process.env.SHOP_SERVICE_URL || 'http://localhost:3003';

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

async function postJson(url, payload) {
  const requestOptions = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  };
  if (mtlsAgent && url.startsWith('https://')) {
    requestOptions.agent = mtlsAgent;
  }
  const response = await fetchImpl(url, requestOptions);
  if (!response.ok) {
    const text = await response.text();
    const message = text || `Request failed with status ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

async function register(req, res) {
  try {
    const {
      email,
      password,
      role,
      name,
      shopName,
      shopDescription,
      legalEntityType,
      taxCode,
      invoiceProvider,
      invoiceRequestMode
    } = req.body;
    if (!email || !password) {
      return res.status(400).json({ message: 'Email and password are required' });
    }
    const existing = await User.findOne({ email });
    if (existing) {
      return res.status(409).json({ message: 'Email already registered' });
    }
    if (role === 'admin') {
      return res.status(403).json({ message: 'Admin registration is disabled' });
    }
    const normalizedRole = role === 'seller' ? 'seller' : 'buyer';
    const buyerName = (name || '').trim();
    const normalizedShopName = (shopName || '').trim();
    if (normalizedRole === 'seller' && !normalizedShopName) {
      return res.status(400).json({ message: 'Shop name is required for sellers' });
    }
    const hash = await bcrypt.hash(password, 10);
    const user = await User.create({
      email,
      password: hash,
      role: normalizedRole,
      isActive: true,
      tokenVersion: 0
    });

    try {
      if (normalizedRole === 'buyer') {
        await postJson(`${USER_SERVICE_URL}/users`, {
          userId: user._id.toString(),
          name: buyerName
        });
      } else {
        const shop = await postJson(`${SHOP_SERVICE_URL}/shops`, {
          name: normalizedShopName,
          ownerId: user._id.toString(),
          description: shopDescription || '',
          invoiceEligible: true,
          invoiceRequestMode: invoiceRequestMode || 'chat_required',
          legalEntityType: legalEntityType || 'unknown',
          taxCode: taxCode || '',
          invoiceProvider: invoiceProvider || ''
        });
        user.shopId = shop?._id || shop?.id || null;
        await user.save();
      }
    } catch (err) {
      await User.findByIdAndDelete(user._id);
      return res.status(502).json({ message: 'Register failed', error: err.message });
    }

    return res.status(201).json({
      id: user._id,
      email: user.email,
      role: user.role,
      shopId: user.shopId || null,
      isActive: user.isActive
    });
  } catch (err) {
    return res.status(500).json({ message: 'Register failed', error: err.message });
  }
}

async function login(req, res) {
  try {
    const { email, password, role } = req.body;
    if (!email || !password) {
      return res.status(400).json({ message: 'Email and password are required' });
    }
    const user = await User.findOne({ email });
    if (!user) {
      return res.status(401).json({ message: 'Invalid credentials' });
    }
    if (!user.isActive) {
      return res.status(403).json({ message: 'Account is locked' });
    }
    if (role && role !== user.role) {
      return res.status(403).json({ message: 'Role mismatch for this account' });
    }
    const ok = await bcrypt.compare(password, user.password);
    if (!ok) {
      return res.status(401).json({ message: 'Invalid credentials' });
    }
    const token = jwt.sign(
      {
        id: user._id,
        email: user.email,
        role: user.role,
        shopId: user.shopId || null,
        tokenVersion: Number(user.tokenVersion || 0)
      },
      process.env.JWT_SECRET || 'devsecret',
      { expiresIn: '7d' }
    );
    return res.json({
      token,
      user: {
        id: user._id,
        email: user.email,
        role: user.role,
        shopId: user.shopId || null,
        isActive: user.isActive
      }
    });
  } catch (err) {
    return res.status(500).json({ message: 'Login failed', error: err.message });
  }
}

async function validateSession(req, res) {
  try {
    const userId = req.query.userId || req.body?.userId;
    if (!userId) {
      return res.status(400).json({ message: 'userId is required' });
    }
    const user = await User.findById(userId);
    if (!user) {
      return res.status(404).json({ message: 'User not found' });
    }
    return res.json({
      id: user._id,
      email: user.email,
      role: user.role,
      shopId: user.shopId || null,
      isActive: user.isActive,
      tokenVersion: Number(user.tokenVersion || 0)
    });
  } catch (err) {
    return res.status(500).json({ message: 'Validate session failed', error: err.message });
  }
}

async function validateToken(req, res) {
  try {
    const token = req.body?.token;
    if (!token) {
      return res.status(400).json({ message: 'token is required' });
    }
    const decoded = jwt.verify(token, process.env.JWT_SECRET || 'devsecret');
    const user = await User.findById(decoded.id);
    if (!user) {
      return res.status(404).json({ message: 'User not found' });
    }
    if (!user.isActive || Number(user.tokenVersion || 0) !== Number(decoded.tokenVersion || 0)) {
      return res.status(401).json({ message: 'Session expired' });
    }
    return res.json({
      user: {
        id: String(user._id),
        email: user.email,
        role: user.role,
        shopId: user.shopId || null,
        isActive: user.isActive,
        tokenVersion: Number(user.tokenVersion || 0)
      }
    });
  } catch (err) {
    if (err?.name === 'TokenExpiredError') {
      return res.status(401).json({ message: 'Token expired' });
    }
    return res.status(401).json({ message: 'Invalid token' });
  }
}

async function getAdminUsers(req, res) {
  try {
    const rows = await User.find().sort({ createdAt: -1 });
    const users = rows.map((item) => ({
      id: item._id,
      email: item.email,
      role: item.role,
      shopId: item.shopId || null,
      isActive: item.isActive !== false,
      tokenVersion: Number(item.tokenVersion || 0),
      createdAt: item.createdAt
    }));
    return res.json(users);
  } catch (err) {
    return res.status(500).json({ message: 'Get users failed', error: err.message });
  }
}

async function lockUser(req, res) {
  try {
    const { id } = req.params;
    const user = await User.findById(id);
    if (!user) {
      return res.status(404).json({ message: 'User not found' });
    }
    if (user.role === 'admin') {
      return res.status(400).json({ message: 'Cannot lock admin account' });
    }
    user.isActive = false;
    user.tokenVersion = Number(user.tokenVersion || 0) + 1;
    await user.save();
    return res.json({
      id: user._id,
      isActive: user.isActive,
      tokenVersion: Number(user.tokenVersion || 0)
    });
  } catch (err) {
    return res.status(500).json({ message: 'Lock user failed', error: err.message });
  }
}

async function unlockUser(req, res) {
  try {
    const { id } = req.params;
    const user = await User.findById(id);
    if (!user) {
      return res.status(404).json({ message: 'User not found' });
    }
    user.isActive = true;
    user.tokenVersion = Number(user.tokenVersion || 0) + 1;
    await user.save();
    return res.json({
      id: user._id,
      isActive: user.isActive,
      tokenVersion: Number(user.tokenVersion || 0)
    });
  } catch (err) {
    return res.status(500).json({ message: 'Unlock user failed', error: err.message });
  }
}

module.exports = {
  register,
  login,
  validateSession,
  validateToken,
  getAdminUsers,
  lockUser,
  unlockUser
};
