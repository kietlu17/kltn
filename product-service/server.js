require('dotenv').config();
const path = require('path');
const fs = require('fs');
const https = require('https');
const express = require('express');
const cors = require('cors');
const morgan = require('morgan');
const { connectMongo } = require('./src/config/db');
const productRoutes = require('./src/routes/productRoutes');
const categoryRoutes = require('./src/routes/categoryRoutes');
const { initProducer } = require('./src/kafka/producer');
const { backfillModerationStatus } = require('./src/services/moderationBackfill');

const app = express();
app.use(cors());
app.use(express.json());
app.use(morgan('dev'));

const uploadsDir = path.join(__dirname, 'uploads');
if (!fs.existsSync(uploadsDir)) {
  fs.mkdirSync(uploadsDir, { recursive: true });
}

app.use('/uploads', express.static(uploadsDir));
app.use('/products', productRoutes);
app.use('/categories', categoryRoutes);

const PORT = process.env.PORT || 3004;

function asBool(value, defaultValue = false) {
  if (value == null) return defaultValue;
  return String(value).toLowerCase() === 'true';
}

function startServer() {
  const tlsEnabled = asBool(process.env.TLS_ENABLED, false);
  if (!tlsEnabled) {
    app.listen(PORT, () => {
      console.log(`Product Service running on port ${PORT}`);
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
    console.log(`Product Service running with TLS on port ${PORT}`);
  });
}

connectMongo().then(async () => {
  await backfillModerationStatus();
  await initProducer();
  startServer();
});
