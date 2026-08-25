const fs = require('fs');
const https = require('https');
const fetchImpl = require('node-fetch');

const productServiceUrl = process.env.PRODUCT_SERVICE_URL || 'http://localhost:3004';

function createMtlsAgent() {
  if (process.env.MTLS_ENABLED !== 'true') return null;
  const caPath = process.env.MTLS_CA_PATH || process.env.TLS_CA_PATH;
  const certPath = process.env.MTLS_CLIENT_CERT_PATH || process.env.TLS_CERT_PATH;
  const keyPath = process.env.MTLS_CLIENT_KEY_PATH || process.env.TLS_KEY_PATH;
  if (!caPath || !certPath || !keyPath) return null;
  return new https.Agent({
    ca: fs.readFileSync(caPath),
    cert: fs.readFileSync(certPath),
    key: fs.readFileSync(keyPath),
    rejectUnauthorized: process.env.MTLS_REJECT_UNAUTHORIZED !== 'false'
  });
}

const mtlsAgent = createMtlsAgent();

async function getProduct(productId, headers = {}) {
  const options = { headers };
  if (mtlsAgent && productServiceUrl.startsWith('https://')) {
    options.agent = mtlsAgent;
  }
  const response = await fetchImpl(`${productServiceUrl}/products/${productId}`, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Product request failed with ${response.status}`);
  }
  return response.json();
}

module.exports = { getProduct };
