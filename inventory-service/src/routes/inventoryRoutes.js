const express = require('express');
const {
  getInventory,
  updateInventory,
  syncProduct,
  reserveInventory,
  releaseInventory,
  commitInventory
} = require('../controllers/inventoryController');

const router = express.Router();

router.post('/reserve', reserveInventory);
router.post('/release', releaseInventory);
router.post('/commit', commitInventory);
router.post('/sync-product', syncProduct);
router.get('/products/:productId', getInventory);
router.patch('/products/:productId', updateInventory);
router.patch('/products/:productId/variants/:variantId', updateInventory);
router.get('/:productId', getInventory);
router.put('/:productId', updateInventory);

module.exports = router;
