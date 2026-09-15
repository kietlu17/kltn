const fs = require('fs');
const path = require('path');
const {
  S3Client,
  CreateBucketCommand,
  HeadBucketCommand,
  GetObjectCommand,
  PutObjectCommand
} = require('@aws-sdk/client-s3');

const bucket = process.env.PRODUCT_IMAGE_BUCKET || 'product-images';
const endpoint = process.env.MINIO_ENDPOINT || process.env.PRODUCT_IMAGE_S3_ENDPOINT || 'http://minio:9000';
const region = process.env.MINIO_REGION || process.env.PRODUCT_IMAGE_REGION || 'us-east-1';
const accessKeyId = process.env.MINIO_ROOT_USER || process.env.MINIO_ACCESS_KEY || 'minioadmin';
const secretAccessKey = process.env.MINIO_ROOT_PASSWORD || process.env.MINIO_SECRET_KEY || 'minioadmin';
const publicBaseUrl = String(process.env.PRODUCT_IMAGE_PUBLIC_BASE_URL || '').replace(/\/+$/, '');
const localUploadsDir = path.join(__dirname, '../../uploads');

const s3 = new S3Client({
  endpoint,
  region,
  forcePathStyle: true,
  credentials: {
    accessKeyId,
    secretAccessKey
  }
});

function normalizeObjectKey(value = '') {
  let next = String(value);
  if (publicBaseUrl && next.startsWith(publicBaseUrl)) {
    next = next.slice(publicBaseUrl.length);
  }
  return next
    .replace(/^https?:\/\/[^/]+\/+/, '')
    .replace(new RegExp(`^${bucket.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\/+`), '')
    .replace(/^\/?uploads\/+/, '')
    .replace(/^\/+/, '')
    .replace(/\.\.+/g, '')
    .replace(/\\/g, '/');
}

function publicUploadPath(key) {
  const normalized = normalizeObjectKey(key);
  if (publicBaseUrl) {
    return `${publicBaseUrl}/${normalized.split('/').map(encodeURIComponent).join('/')}`;
  }
  return `/uploads/${normalized}`;
}

function extensionFromFile(file) {
  const original = path.extname(file.originalname || '').toLowerCase();
  if (original && original.length <= 8) return original;
  const subtype = String(file.mimetype || '').split('/')[1] || 'bin';
  return `.${subtype.replace(/[^a-z0-9]/gi, '').slice(0, 8) || 'bin'}`;
}

function buildObjectKey(file, prefix = 'products') {
  const ext = extensionFromFile(file);
  const random = Math.round(Math.random() * 1e9);
  return `${prefix}/${Date.now()}-${random}${ext}`;
}

async function ensureProductImageBucket() {
  try {
    await s3.send(new HeadBucketCommand({ Bucket: bucket }));
  } catch (err) {
    const status = err?.$metadata?.httpStatusCode;
    if (![301, 403, 404].includes(status)) throw err;
    if (status === 403) return;
    await s3.send(new CreateBucketCommand({ Bucket: bucket }));
  }
}

async function uploadProductFile(file, prefix = 'products') {
  if (!file?.buffer) return '';
  await ensureProductImageBucket();
  const key = buildObjectKey(file, prefix);
  await s3.send(new PutObjectCommand({
    Bucket: bucket,
    Key: key,
    Body: file.buffer,
    ContentType: file.mimetype || 'application/octet-stream'
  }));
  return publicUploadPath(key);
}

async function getProductImageStream(rawKey) {
  const key = normalizeObjectKey(rawKey);
  const response = await s3.send(new GetObjectCommand({ Bucket: bucket, Key: key }));
  return {
    body: response.Body,
    contentType: response.ContentType || 'application/octet-stream',
    contentLength: response.ContentLength,
    cacheControl: response.CacheControl
  };
}

function getLocalUploadPath(rawKey) {
  const key = normalizeObjectKey(rawKey);
  return path.join(localUploadsDir, key);
}

function hasLocalUpload(rawKey) {
  return fs.existsSync(getLocalUploadPath(rawKey));
}

module.exports = {
  bucket,
  normalizeObjectKey,
  publicUploadPath,
  ensureProductImageBucket,
  uploadProductFile,
  getProductImageStream,
  getLocalUploadPath,
  hasLocalUpload
};
