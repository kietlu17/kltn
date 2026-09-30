require('dotenv').config();
const fs = require('fs');
const https = require('https');
const express = require('express');
const cors = require('cors');
const morgan = require('morgan');
const mongoose = require('mongoose');

const app = express();
app.use(cors());
app.use(express.json({ limit: '1mb' }));
app.use(morgan('dev'));

const conversationSchema = new mongoose.Schema({
  _id: { type: String, required: true },
  shopId: { type: String, required: true, index: true },
  buyerId: { type: String, required: true, index: true },
  buyerName: { type: String, default: 'Buyer' },
  product: { type: Object, default: null },
  lastMessage: { type: String, default: '' },
  createdAt: { type: Date, default: Date.now },
  updatedAt: { type: Date, default: Date.now }
});

const messageSchema = new mongoose.Schema({
  _id: { type: String, required: true },
  conversationId: { type: String, required: true, index: true },
  senderRole: { type: String, required: true },
  senderId: { type: String, default: null },
  text: { type: String, required: true },
  createdAt: { type: Date, default: Date.now }
});

const Conversation = mongoose.model('Conversation', conversationSchema);
const Message = mongoose.model('Message', messageSchema);

function buildConversationId(shopId, buyerId) {
  return `${shopId}::${buyerId}`;
}

function normalizeConversation(doc) {
  const obj = doc.toObject({ getters: false, virtuals: false });
  return {
    id: obj._id,
    shopId: obj.shopId,
    buyerId: obj.buyerId,
    buyerName: obj.buyerName,
    product: obj.product,
    lastMessage: obj.lastMessage || null,
    createdAt: obj.createdAt,
    updatedAt: obj.updatedAt
  };
}

const router = express.Router();

router.post('/conversations', async (req, res) => {
  try {
    const { shopId, buyerId, buyerName, product } = req.body || {};
    if (!shopId || !buyerId) {
      return res.status(400).json({ message: 'shopId and buyerId are required' });
    }
    const id = buildConversationId(shopId, buyerId);
    let conversation = await Conversation.findById(id);
    if (!conversation) {
      conversation = new Conversation({
        _id: id,
        shopId,
        buyerId,
        buyerName: buyerName || 'Buyer',
        product: product || null,
        createdAt: new Date(),
        updatedAt: new Date()
      });
    } else {
      if (buyerName) conversation.buyerName = buyerName;
      if (product) conversation.product = product;
      conversation.updatedAt = new Date();
    }
    await conversation.save();
    return res.json(normalizeConversation(conversation));
  } catch (err) {
    return res.status(500).json({ message: 'Create conversation failed', error: err.message });
  }
});

router.get('/shops/:shopId/conversations', async (req, res) => {
  try {
    const { shopId } = req.params;
    const list = await Conversation.find({ shopId }).sort({ updatedAt: -1 });
    return res.json(list.map(normalizeConversation));
  } catch (err) {
    return res.status(500).json({ message: 'Get conversations failed', error: err.message });
  }
});

router.get('/buyers/:buyerId/conversations', async (req, res) => {
  try {
    const { buyerId } = req.params;
    const list = await Conversation.find({ buyerId }).sort({ updatedAt: -1 });
    return res.json(list.map(normalizeConversation));
  } catch (err) {
    return res.status(500).json({ message: 'Get conversations failed', error: err.message });
  }
});

router.get('/conversations/:id/messages', async (req, res) => {
  try {
    const { id } = req.params;
    const conversation = await Conversation.findById(id);
    if (!conversation) {
      return res.status(404).json({ message: 'Conversation not found' });
    }
    const list = await Message.find({ conversationId: id }).sort({ createdAt: 1 });
    return res.json(list.map((msg) => msg.toObject({ getters: false, virtuals: false })));
  } catch (err) {
    return res.status(500).json({ message: 'Get messages failed', error: err.message });
  }
});

router.post('/conversations/:id/messages', async (req, res) => {
  try {
    const { id } = req.params;
    const { senderRole, senderId, text } = req.body || {};
    if (!senderRole || !text) {
      return res.status(400).json({ message: 'senderRole and text are required' });
    }
    const conversation = await Conversation.findById(id);
    if (!conversation) {
      return res.status(404).json({ message: 'Conversation not found' });
    }
    const entry = new Message({
      _id: `${id}-${Date.now()}`,
      conversationId: id,
      senderRole,
      senderId: senderId || null,
      text: String(text).slice(0, 2000),
      createdAt: new Date()
    });
    await entry.save();
    conversation.lastMessage = entry.text;
    conversation.updatedAt = entry.createdAt;
    await conversation.save();
    return res.status(201).json(entry.toObject({ getters: false, virtuals: false }));
  } catch (err) {
    return res.status(500).json({ message: 'Send message failed', error: err.message });
  }
});

app.use('/chat', router);

async function connectMongo() {
  const uri = process.env.MONGO_URI || 'mongodb://localhost:27017/chat-service';
  mongoose.set('strictQuery', true);
  await mongoose.connect(uri);
  console.log('Chat Service connected to MongoDB');
}

const PORT = process.env.PORT || 3009;

function asBool(value, defaultValue = false) {
  if (value == null) return defaultValue;
  return String(value).toLowerCase() === 'true';
}

function startServer() {
  const tlsEnabled = asBool(process.env.TLS_ENABLED, false);
  if (!tlsEnabled) {
    app.listen(PORT, () => {
      console.log(`Chat Service running on port ${PORT}`);
    });
    return;
  }

  const options = {
    key: fs.readFileSync(process.env.TLS_KEY_PATH),
    cert: fs.readFileSync(process.env.TLS_CERT_PATH),
    ca: fs.readFileSync(process.env.TLS_CA_PATH)
  };

  if (asBool(process.env.TLS_REQUEST_CLIENT_CERT, true)) {
    options.requestCert = true;
    options.rejectUnauthorized = asBool(process.env.TLS_REJECT_UNAUTHORIZED, true);
  }

  https.createServer(options, app).listen(PORT, () => {
    console.log(`Chat Service running with TLS on port ${PORT}`);
  });
}

connectMongo().then(() => {
  startServer();
});
