const express = require('express');
const multer = require('multer');
const path = require('path');
const {
  createProduct,
  getProducts,
  getProductById,
  updateProduct,
  deleteProduct,
  getPendingProducts,
  moderateProduct,
  deleteProductByAdmin
} = require('../controllers/productController');

const router = express.Router();

const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    cb(null, path.join(__dirname, '../../uploads'));
  },
  filename: (req, file, cb) => {
    const unique = `${Date.now()}-${Math.round(Math.random() * 1e9)}`;
    const ext = path.extname(file.originalname);
    cb(null, `${unique}${ext}`);
  }
});

const upload = multer({ storage });

router.post('/', upload.any(), createProduct);
router.get('/admin/pending', getPendingProducts);
router.patch('/admin/:id/moderate', moderateProduct);
router.delete('/admin/:id', deleteProductByAdmin);
router.get('/', getProducts);
router.get('/:id', getProductById);
router.put('/:id', upload.any(), updateProduct);
router.delete('/:id', deleteProduct);

module.exports = router;
