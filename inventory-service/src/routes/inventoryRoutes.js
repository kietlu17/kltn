const express = require('express');
const { getInventory, updateInventory } = require('../controllers/inventoryController');

const router = express.Router();

router.get('/:productId', getInventory);
router.put('/:productId', updateInventory);

module.exports = router;
