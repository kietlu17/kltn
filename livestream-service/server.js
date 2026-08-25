require('dotenv').config();
const fs = require('fs');
const https = require('https');
const express = require('express');
const cors = require('cors');
const morgan = require('morgan');
const { connectMongo } = require('./src/config/db');
const liveRoutes = require('./src/routes/liveRoutes');
const { initProducer } = require('./src/kafka/producer');
const { startStatsFlush, startReconcileJob } = require('./src/services/liveMaintenance');

const app = express();
app.use(cors());
app.use(express.json({
  limit: '1mb',
  verify: (req, res, buffer) => {
    req.rawBody = buffer.toString('utf8');
  }
}));
app.use(morgan('dev'));

app.use('/lives', liveRoutes);

const PORT = process.env.PORT || 3014;

function asBool(value, defaultValue = false) {
  if (value == null) return defaultValue;
  return String(value).toLowerCase() === 'true';
}

function startServer() {
  const tlsEnabled = asBool(process.env.TLS_ENABLED, false);
  if (!tlsEnabled) {
    app.listen(PORT, () => {
      console.log(`Livestream Service running on port ${PORT}`);
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
    console.log(`Livestream Service running with TLS on port ${PORT}`);
  });
}

connectMongo().then(async () => {
  await initProducer();
  startStatsFlush();
  startReconcileJob();
  startServer();
});
