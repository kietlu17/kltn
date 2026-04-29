const express = require('express');
const { addToCart, removeFromCart, updateQuantity, getCart } = require('../controllers/cartController');

const router = express.Router();

router.post('/add', addToCart);
router.post('/remove', removeFromCart);
router.post('/update', updateQuantity);
router.get('/:userId', getCart);

module.exports = router;
