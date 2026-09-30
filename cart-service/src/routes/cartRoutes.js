const express = require('express');
const { addToCart, upsertCartLine, removeFromCart, updateQuantity, getCart } = require('../controllers/cartController');

const router = express.Router();

router.post('/add', addToCart);
router.put('/items', upsertCartLine);
router.post('/remove', removeFromCart);
router.post('/update', updateQuantity);
router.get('/user', getCart);
router.get('/:userId', getCart);

module.exports = router;
