const Cart = require('../models/Cart');

function isSameLine(item, productId, variantId) {
  return item.productId === productId && String(item.variantId || '') === String(variantId || '');
}

async function addToCart(req, res) {
  try {
    const { userId, productId, quantity, variantId } = req.body;
    if (!userId || !productId || !quantity) {
      return res.status(400).json({ message: 'userId, productId, quantity are required' });
    }
    let cart = await Cart.findOne({ userId });
    if (!cart) {
      cart = await Cart.create({ userId, products: [{ productId, variantId: variantId || null, quantity }] });
      return res.status(201).json(cart);
    }
    const existing = cart.products.find((p) => isSameLine(p, productId, variantId));
    if (existing) {
      existing.quantity += Number(quantity);
    } else {
      cart.products.push({ productId, variantId: variantId || null, quantity });
    }
    await cart.save();
    return res.json(cart);
  } catch (err) {
    return res.status(500).json({ message: 'Add to cart failed', error: err.message });
  }
}

async function removeFromCart(req, res) {
  try {
    const { userId, productId, variantId } = req.body;
    if (!userId || !productId) {
      return res.status(400).json({ message: 'userId and productId are required' });
    }
    const cart = await Cart.findOne({ userId });
    if (!cart) {
      return res.status(404).json({ message: 'Cart not found' });
    }
    cart.products = cart.products.filter((p) => !isSameLine(p, productId, variantId));
    await cart.save();
    return res.json(cart);
  } catch (err) {
    return res.status(500).json({ message: 'Remove from cart failed', error: err.message });
  }
}

async function updateQuantity(req, res) {
  try {
    const { userId, productId, variantId, quantity } = req.body;
    if (!userId || !productId || quantity == null) {
      return res.status(400).json({ message: 'userId, productId, quantity are required' });
    }
    const cart = await Cart.findOne({ userId });
    if (!cart) {
      return res.status(404).json({ message: 'Cart not found' });
    }
    const item = cart.products.find((p) => isSameLine(p, productId, variantId));
    if (!item) {
      return res.status(404).json({ message: 'Product not in cart' });
    }
    item.quantity = Number(quantity);
    await cart.save();
    return res.json(cart);
  } catch (err) {
    return res.status(500).json({ message: 'Update cart failed', error: err.message });
  }
}

async function getCart(req, res) {
  try {
    const userId = req.params.userId || req.headers['x-user-id'];
    if (!userId) {
      return res.status(400).json({ message: 'userId is required' });
    }
    const cart = await Cart.findOne({ userId });
    if (!cart) {
      return res.json({ userId, products: [] });
    }
    return res.json(cart);
  } catch (err) {
    return res.status(500).json({ message: 'Get cart failed', error: err.message });
  }
}

module.exports = { addToCart, removeFromCart, updateQuantity, getCart };
