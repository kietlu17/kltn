require('dotenv').config();
const fs = require('fs');
const https = require('https');
const express = require('express');
const cors = require('cors');
const morgan = require('morgan');
const { initDb } = require('./src/config/db');
require('./src/models');
const { initProducer, initOutboxPublisher } = require('./src/kafka/producer');
const { initConsumer } = require('./src/kafka/consumer');
const { initSettlementWorker } = require('./src/services/settlementService');
const walletRoutes = require('./src/routes/walletRoutes');

const app = express();
app.use(cors());
app.use(express.json());
app.use(morgan('dev'));

app.get('/wallets/health', (req, res) => {
  res.json({ status: 'ok', service: 'wallet-service' });
});
app.use('/wallets', walletRoutes);
app.use('/payments/wallet', walletRoutes);

const PORT = process.env.PORT || 3011;

function asBool(value, defaultValue = false) {
  if (value == null) return defaultValue;
  return String(value).toLowerCase() === 'true';
}

function startServer() {
  const tlsEnabled = asBool(process.env.TLS_ENABLED, false);
  if (!tlsEnabled) {
    app.listen(PORT, () => console.log(`Wallet Service running on port ${PORT}`));
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
    console.log(`Wallet Service running with TLS on port ${PORT}`);
  });
}

async function start() {
  await initDb();
  await initProducer();
  initOutboxPublisher();
  initSettlementWorker();
  await initConsumer();
  startServer();
}

start().catch((err) => {
  console.error('Wallet Service failed to start', err);
  process.exit(1);
});
