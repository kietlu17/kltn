const express = require('express');
const multer = require('multer');
const {
  createProduct,
  getProducts,
  getProductsByIds,
  getProductById,
  updateProduct,
  deleteProduct,
  getPendingProducts,
  moderateProduct,
  deleteProductByAdmin
} = require('../controllers/productController');

const router = express.Router();

const upload = multer({ storage: multer.memoryStorage() });

router.post('/', upload.any(), createProduct);
router.get('/admin/pending', getPendingProducts);
router.patch('/admin/:id/moderate', moderateProduct);
router.delete('/admin/:id', deleteProductByAdmin);
router.get('/', getProducts);
router.get('/batch', getProductsByIds);
router.get('/:id', getProductById);
router.put('/:id', upload.any(), updateProduct);
router.delete('/:id', deleteProduct);

module.exports = router;
