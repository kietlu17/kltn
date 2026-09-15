const Product = require('../models/Product');
const Category = require('../models/Category');
const mongoose = require('mongoose');
const { publishProductCreated, publishProductUpdated } = require('../kafka/producer');
const { evaluateProductContent } = require('../moderation/keywordRules');
const { uploadProductFile } = require('../services/objectStorage');

function parseNumber(value, fallback = 0) {
  const parsed = Number(value);
  if (Number.isFinite(parsed)) return parsed;
  return fallback;
}

function parsePositiveInteger(value, fallback, max = Number.MAX_SAFE_INTEGER) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 1) return fallback;
  return Math.min(Math.trunc(parsed), max);
}

function parseProductsPagination(query = {}) {
  const enabled =
    String(query.paginated || '').toLowerCase() === 'true' ||
    query.page != null ||
    query.limit != null;
  const maxLimit = parsePositiveInteger(process.env.PRODUCTS_MAX_PAGE_SIZE, 100, 500);
  const defaultLimit = parsePositiveInteger(process.env.PRODUCTS_DEFAULT_PAGE_SIZE, 24, maxLimit);
  return {
    enabled,
    page: parsePositiveInteger(query.page, 1),
    limit: parsePositiveInteger(query.limit, defaultLimit, maxLimit)
  };
}

function buildProductsSort(sort) {
  const sortMap = {
    newest: { createdAt: -1, _id: -1 },
    price_asc: { price: 1, createdAt: -1, _id: -1 },
    price_desc: { price: -1, createdAt: -1, _id: -1 },
    sold_desc: { sold: -1, createdAt: -1, _id: -1 }
  };
  return sortMap[sort] || sortMap.newest;
}

function parseProductIds(value, max = 100) {
  return [...new Set(String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter((item) => mongoose.Types.ObjectId.isValid(item)))]
    .slice(0, max);
}

function parsePriceValue(value, fallback = NaN) {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.round(value);
  }
  const raw = String(value ?? '').trim();
  if (!raw) return fallback;

  const sanitized = raw.replace(/[^\d.,-]/g, '');
  if (!sanitized) return fallback;

  if (/^-?\d+$/.test(sanitized)) {
    const parsedInt = Number(sanitized);
    return Number.isFinite(parsedInt) ? parsedInt : fallback;
  }

  if (/^-?\d{1,3}([.,]\d{3})+$/.test(sanitized)) {
    const noGrouping = sanitized.replace(/[.,]/g, '');
    const parsedGrouped = Number(noGrouping);
    return Number.isFinite(parsedGrouped) ? parsedGrouped : fallback;
  }

  const normalizedDecimal = sanitized.replace(',', '.');
  const parsedDecimal = Number(normalizedDecimal);
  if (Number.isFinite(parsedDecimal)) return Math.round(parsedDecimal);
  return fallback;
}

function normalizePricePair(rawOriginalPrice, rawSalePrice) {
  const salePrice = parsePriceValue(rawSalePrice, NaN);
  const originalPrice =
    rawOriginalPrice == null || rawOriginalPrice === ''
      ? salePrice
      : parsePriceValue(rawOriginalPrice, NaN);

  if (!Number.isFinite(salePrice) || salePrice < 0) {
    throw new Error('price must be a non-negative number');
  }
  if (!Number.isFinite(originalPrice) || originalPrice < 0) {
    throw new Error('originalPrice must be a non-negative number');
  }
  if (originalPrice < salePrice) {
    throw new Error('originalPrice must be greater than or equal to price');
  }

  return { originalPrice, price: salePrice };
}

function parseVariants(rawVariants) {
  if (rawVariants == null || rawVariants === '') return [];
  let input = rawVariants;
  if (typeof rawVariants === 'string') {
    try {
      input = JSON.parse(rawVariants);
    } catch {
      throw new Error('variants must be valid JSON');
    }
  }
  if (!Array.isArray(input)) {
    throw new Error('variants must be an array');
  }

  const normalized = input
    .map((item) => {
      const existingId = item?._id != null ? String(item._id).trim() : '';
      const rawPrice = parsePriceValue(item?.price, NaN);
      const rawOriginalPrice =
        item?.originalPrice == null || item?.originalPrice === ''
          ? rawPrice
          : parsePriceValue(item?.originalPrice, NaN);
      const normalizedItem = {
        name: String(item?.name || '').trim(),
        sku: String(item?.sku || '').trim(),
        imageUrl: String(item?.imageUrl || '').trim(),
        originalPrice: rawOriginalPrice,
        price: rawPrice,
        quantity: parseNumber(item?.quantity, NaN)
      };
      if (existingId) normalizedItem._id = existingId;
      return normalizedItem;
    })
    .filter((item) => item.name || item.sku || Number.isFinite(item.price) || Number.isFinite(item.quantity));

  normalized.forEach((item) => {
    if (!item.name) {
      throw new Error('Each variant requires a name');
    }
    if (!Number.isFinite(item.price) || item.price < 0) {
      throw new Error('Each variant requires a non-negative price');
    }
    if (!Number.isFinite(item.originalPrice) || item.originalPrice < 0) {
      throw new Error('Each variant requires a non-negative originalPrice');
    }
    if (item.originalPrice < item.price) {
      throw new Error('Each variant originalPrice must be greater than or equal to price');
    }
    if (!Number.isFinite(item.quantity) || item.quantity < 0) {
      throw new Error('Each variant requires a non-negative quantity');
    }
  });

  return normalized;
}

async function splitUploadedFiles(files = []) {
  const all = Array.isArray(files) ? files : [];
  const productImages = await Promise.all(
    all
      .filter((file) => file?.fieldname === 'images')
      .map((file) => uploadProductFile(file))
  );
  const variantImages = new Map();
  await Promise.all(all.map(async (file) => {
    const match = String(file?.fieldname || '').match(/^variantImage_(\d+)$/);
    if (!match) return;
    const index = Number(match[1]);
    if (!Number.isInteger(index) || index < 0) return;
    variantImages.set(index, await uploadProductFile(file, 'variants'));
  }));
  return { productImages: productImages.filter(Boolean), variantImages };
}

function attachVariantImages(variants, variantImages) {
  if (!Array.isArray(variants) || !variantImages || variantImages.size === 0) return variants;
  return variants.map((variant, index) => {
    if (!variantImages.has(index)) return variant;
    return { ...variant, imageUrl: variantImages.get(index) };
  });
}

function preserveExistingVariantIds(existingVariants, nextVariants) {
  const existingById = new Map(
    (Array.isArray(existingVariants) ? existingVariants : []).map((variant) => [String(variant._id), variant._id])
  );
  return (Array.isArray(nextVariants) ? nextVariants : []).map((variant) => {
    const next = { ...variant };
    const key = next._id != null ? String(next._id) : '';
    if (key && existingById.has(key)) {
      next._id = existingById.get(key);
    }
    return next;
  });
}

function summarizeVariants(variants) {
  if (!Array.isArray(variants) || variants.length === 0) {
    return { minPrice: null, minOriginalPrice: null, totalQuantity: null };
  }
  const minPrice = Math.min(...variants.map((item) => Number(item.price || 0)));
  const minOriginalPrice = Math.min(
    ...variants.map((item) => Number(item.originalPrice ?? item.price ?? 0))
  );
  const totalQuantity = variants.reduce((sum, item) => sum + Number(item.quantity || 0), 0);
  return { minPrice, minOriginalPrice, totalQuantity };
}

function buildModerationFields({ name, description, detail }) {
  const evaluation = evaluateProductContent({ name, description, detail });
  if (evaluation.flagged) {
    const matches = [...new Set(evaluation.matches)];
    return {
      moderationStatus: 'pending',
      moderatedBy: 'system-rule',
      moderatedAt: new Date(),
      moderationNote: `Flagged by keyword rule: ${matches.join(', ')}`,
      moderationKeywordMatches: matches,
      sellerModerationMessage: `San pham cua ban chua tu khoa vi pham: ${matches.join(
        ', '
      )}. Vui long chinh sua noi dung va cap nhat lai.`
    };
  }
  return {
    moderationStatus: 'approved',
    moderatedBy: 'system-rule',
    moderatedAt: new Date(),
    moderationNote: 'Auto-approved by keyword rule',
    moderationKeywordMatches: [],
    sellerModerationMessage: 'San pham da qua kiem duyet tu dong.'
  };
}

function recalcProductSummary(product) {
  const variants = Array.isArray(product.variants) ? product.variants : [];
  if (!variants.length) return;
  const { minPrice, minOriginalPrice, totalQuantity } = summarizeVariants(variants);
  product.price = minPrice;
  product.originalPrice = minOriginalPrice;
  product.quantity = totalQuantity;
}

async function createProduct(req, res) {
  try {
    const { name, description, detail, shopId } = req.body;
    const categoryId = req.body.categoryId || null;
    let variants = parseVariants(req.body.variants);

    let originalPrice = NaN;
    let price = NaN;
    let quantity = req.body.quantity != null ? Number(req.body.quantity) : 0;

    if (!name || !shopId) {
      return res.status(400).json({ message: 'name and shopId are required' });
    }

    if (variants.length > 0) {
      const summary = summarizeVariants(variants);
      price = summary.minPrice;
      originalPrice = summary.minOriginalPrice;
      quantity = summary.totalQuantity;
    } else {
      const pricePair = normalizePricePair(req.body.originalPrice, req.body.price);
      originalPrice = pricePair.originalPrice;
      price = pricePair.price;
      if (!Number.isFinite(quantity) || quantity < 0) {
        return res.status(400).json({ message: 'quantity must be a non-negative number' });
      }
    }

    if (categoryId) {
      const category = await Category.findOne({ _id: categoryId, shopId });
      if (!category) {
        return res.status(400).json({ message: 'Invalid category for this shop' });
      }
    }

    const { productImages, variantImages } = await splitUploadedFiles(req.files);
    const images = productImages;
    variants = attachVariantImages(variants, variantImages);
    const moderation = buildModerationFields({ name, description, detail });

    const product = await Product.create({
      name,
      originalPrice,
      price,
      description,
      detail,
      images,
      quantity,
      variants,
      shopId,
      categoryId,
      ...moderation
    });

    await publishProductCreated(product);

    return res.status(201).json({
      ...product.toObject(),
      autoModeration: moderation.moderationStatus,
      moderationNote: moderation.moderationNote,
      moderationAlert: {
        flagged: moderation.moderationStatus === 'pending',
        keywords: moderation.moderationKeywordMatches,
        message: moderation.sellerModerationMessage
      }
    });
  } catch (err) {
    if (/variant|price must|originalPrice must|quantity must/i.test(err.message || '')) {
      return res.status(400).json({ message: err.message });
    }
    return res.status(500).json({ message: 'Create product failed', error: err.message });
  }
}

async function getProducts(req, res) {
  try {
    const { shopId, q, moderationStatus, categoryId, minPrice, maxPrice, sort } = req.query;
    const pagination = parseProductsPagination(req.query);
    const role = req.headers['x-user-role'] || '';
    const requesterShopId = req.headers['x-user-shop-id'] || req.headers['x-user-id'] || '';
    const filter = {};
    if (shopId) filter.shopId = shopId;
    if (categoryId) filter.categoryId = categoryId;
    if (q) filter.name = { $regex: q, $options: 'i' };
    if (moderationStatus) filter.moderationStatus = moderationStatus;
    const minPriceValue = parsePriceValue(minPrice, NaN);
    const maxPriceValue = parsePriceValue(maxPrice, NaN);
    if (Number.isFinite(minPriceValue) || Number.isFinite(maxPriceValue)) {
      filter.price = {};
      if (Number.isFinite(minPriceValue)) filter.price.$gte = minPriceValue;
      if (Number.isFinite(maxPriceValue)) filter.price.$lte = maxPriceValue;
    }

    const isAdmin = role === 'admin';
    const isSellerViewingOwnShop =
      role === 'seller' && shopId && String(shopId) === String(requesterShopId);
    if (!isAdmin && !isSellerViewingOwnShop) {
      filter.moderationStatus = 'approved';
    }
    const sortBy = buildProductsSort(sort);
    if (pagination.enabled) {
      const skip = (pagination.page - 1) * pagination.limit;
      const [products, total] = await Promise.all([
        Product.find(filter).sort(sortBy).skip(skip).limit(pagination.limit),
        Product.countDocuments(filter)
      ]);
      const totalPages = Math.max(1, Math.ceil(total / pagination.limit));
      return res.json({
        items: products,
        pagination: {
          page: pagination.page,
          limit: pagination.limit,
          total,
          totalPages,
          hasNextPage: pagination.page < totalPages,
          hasPrevPage: pagination.page > 1
        }
      });
    }

    const products = await Product.find(filter).sort(sortBy);
    return res.json(products);
  } catch (err) {
    return res.status(500).json({ message: 'Get products failed', error: err.message });
  }
}

async function getProductsByIds(req, res) {
  try {
    const ids = parseProductIds(req.query.ids, 200);
    if (!ids.length) {
      return res.json([]);
    }

    const role = req.headers['x-user-role'] || '';
    const requesterShopId = req.headers['x-user-shop-id'] || req.headers['x-user-id'] || '';
    const filter = { _id: { $in: ids } };
    if (role !== 'admin') {
      filter.$or = [
        { moderationStatus: 'approved' },
        { shopId: String(requesterShopId || '') }
      ];
    }

    const products = await Product.find(filter);
    return res.json(products);
  } catch (err) {
    return res.status(500).json({ message: 'Get product batch failed', error: err.message });
  }
}

async function getProductById(req, res) {
  try {
    const product = await Product.findById(req.params.id);
    if (!product) {
      return res.status(404).json({ message: 'Product not found' });
    }
    const role = req.headers['x-user-role'] || '';
    const requesterShopId = req.headers['x-user-shop-id'] || req.headers['x-user-id'] || '';
    const isAdmin = role === 'admin';
    const isSellerOwner = role === 'seller' && String(product.shopId) === String(requesterShopId);
    if (!isAdmin && !isSellerOwner && product.moderationStatus !== 'approved') {
      return res.status(404).json({ message: 'Product not found' });
    }
    return res.json(product);
  } catch (err) {
    return res.status(500).json({ message: 'Get product failed', error: err.message });
  }
}

async function updateProduct(req, res) {
  try {
    const shopId = req.body.shopId || req.query.shopId;
    if (!shopId) {
      return res.status(400).json({ message: 'shopId is required' });
    }

    const product = await Product.findOne({ _id: req.params.id, shopId });
    if (!product) {
      return res.status(404).json({ message: 'Product not found' });
    }

    const updates = { ...req.body };
    delete updates.shopId;
    delete updates.sold;

    if (updates.categoryId === '') {
      updates.categoryId = null;
    }

    if (updates.categoryId) {
      const category = await Category.findOne({ _id: updates.categoryId, shopId });
      if (!category) {
        return res.status(400).json({ message: 'Invalid category for this shop' });
      }
    }

    if (updates.existingImages) {
      try {
        updates.images = JSON.parse(updates.existingImages);
      } catch {
        updates.images = [];
      }
      delete updates.existingImages;
    }

    const { productImages, variantImages } = await splitUploadedFiles(req.files);
    if (productImages.length) {
      const uploaded = productImages;
      const existing = Array.isArray(updates.images) ? updates.images : product.images || [];
      updates.images = [...existing, ...uploaded];
    }

    let variants = product.variants || [];
    if (Object.prototype.hasOwnProperty.call(req.body, 'variants')) {
      variants = parseVariants(req.body.variants);
      variants = attachVariantImages(variants, variantImages);
      variants = preserveExistingVariantIds(product.variants, variants);
      updates.variants = variants;
    }

    if (variants.length > 0) {
      const summary = summarizeVariants(variants);
      updates.price = summary.minPrice;
      updates.originalPrice = summary.minOriginalPrice;
      updates.quantity = summary.totalQuantity;
    } else {
      if (updates.price != null || updates.originalPrice != null) {
        const nextSalePrice = parsePriceValue(updates.price ?? product.price, NaN);
        const existingOriginalPrice = parsePriceValue(product.originalPrice, NaN);
        const fallbackOriginalPrice =
          Number.isFinite(existingOriginalPrice) && existingOriginalPrice >= nextSalePrice
            ? existingOriginalPrice
            : nextSalePrice;
        const pricePair = normalizePricePair(
          updates.originalPrice ?? fallbackOriginalPrice,
          updates.price ?? product.price
        );
        updates.originalPrice = pricePair.originalPrice;
        updates.price = pricePair.price;
      }
      if (updates.quantity != null) {
        const nextQty = Number(updates.quantity);
        if (!Number.isFinite(nextQty) || nextQty < 0) {
          return res.status(400).json({ message: 'quantity must be a non-negative number' });
        }
        updates.quantity = nextQty;
      }
    }

    Object.keys(updates).forEach((key) => {
      if (updates[key] !== undefined) {
        product[key] = updates[key];
      }
    });

    const moderation = buildModerationFields({
      name: product.name,
      description: product.description,
      detail: product.detail
    });

    product.moderationStatus = moderation.moderationStatus;
    product.moderatedBy = moderation.moderatedBy;
    product.moderatedAt = moderation.moderatedAt;
    product.moderationNote = moderation.moderationNote;

    recalcProductSummary(product);
    await product.save();
    try {
      await publishProductUpdated(product);
    } catch (eventErr) {
      console.error('Publish product.updated failed', eventErr.message);
    }

    return res.json({
      ...product.toObject(),
      autoModeration: moderation.moderationStatus,
      moderationNote: moderation.moderationNote,
      moderationAlert: {
        flagged: moderation.moderationStatus === 'pending',
        keywords: moderation.moderationKeywordMatches,
        message: moderation.sellerModerationMessage
      }
    });
  } catch (err) {
    if (/variant|price must|originalPrice must|quantity must/i.test(err.message || '')) {
      return res.status(400).json({ message: err.message });
    }
    return res.status(500).json({ message: 'Update product failed', error: err.message });
  }
}

async function deleteProduct(req, res) {
  try {
    const { shopId } = req.query;
    if (!shopId) {
      return res.status(400).json({ message: 'shopId is required' });
    }
    const product = await Product.findOneAndDelete({ _id: req.params.id, shopId });
    if (!product) {
      return res.status(404).json({ message: 'Product not found' });
    }
    return res.json({ message: 'Product deleted' });
  } catch (err) {
    return res.status(500).json({ message: 'Delete product failed', error: err.message });
  }
}

async function getPendingProducts(req, res) {
  try {
    const products = await Product.find({ moderationStatus: 'pending' }).sort({ createdAt: -1 });
    return res.json(products);
  } catch (err) {
    return res.status(500).json({ message: 'Get pending products failed', error: err.message });
  }
}

async function moderateProduct(req, res) {
  try {
    const { id } = req.params;
    const { action, note } = req.body || {};
    const mapping = {
      approve: 'approved',
      reject: 'rejected',
      remove: 'removed'
    };
    const nextStatus = mapping[action];
    if (!nextStatus) {
      return res.status(400).json({ message: 'action must be approve, reject, or remove' });
    }
    const updates = {
      moderationStatus: nextStatus,
      moderatedBy: req.headers['x-user-id'] || null,
      moderatedAt: new Date(),
      moderationNote: typeof note === 'string' ? note : ''
    };

    if (nextStatus === 'rejected' || nextStatus === 'removed') {
      updates.$inc = { strikeCount: 1 };
      updates.lastStrikeReason = typeof note === 'string' && note.trim() ? note.trim() : `Admin ${nextStatus}`;
    }

    let product;
    if (updates.$inc) {
      const { $inc, ...rest } = updates;
      product = await Product.findByIdAndUpdate(id, { ...rest, $inc }, { new: true });
    } else {
      product = await Product.findByIdAndUpdate(id, updates, { new: true });
    }

    if (!product) {
      return res.status(404).json({ message: 'Product not found' });
    }
    return res.json(product);
  } catch (err) {
    return res.status(500).json({ message: 'Moderate product failed', error: err.message });
  }
}

async function deleteProductByAdmin(req, res) {
  try {
    const product = await Product.findByIdAndDelete(req.params.id);
    if (!product) {
      return res.status(404).json({ message: 'Product not found' });
    }
    return res.json({ message: 'Product deleted' });
  } catch (err) {
    return res.status(500).json({ message: 'Delete product failed', error: err.message });
  }
}

module.exports = {
  createProduct,
  getProducts,
  getProductsByIds,
  getProductById,
  updateProduct,
  deleteProduct,
  getPendingProducts,
  moderateProduct,
  deleteProductByAdmin
};
