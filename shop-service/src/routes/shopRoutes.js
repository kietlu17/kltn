const express = require('express');
const { createShop, getShops, getShopById } = require('../controllers/shopController');

const router = express.Router();

router.post('/', createShop);
router.get('/', getShops);
router.get('/:id', getShopById);

module.exports = router;
