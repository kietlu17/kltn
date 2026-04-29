const express = require('express');
const {
  createCategory,
  getCategories,
  getCategoryById,
  updateCategory,
  deleteCategory,
  getAdminCategories,
  updateAdminCategory,
  deleteAdminCategory
} = require('../controllers/categoryController');

const router = express.Router();

router.post('/', createCategory);
router.get('/', getCategories);
router.get('/admin/all', getAdminCategories);
router.put('/admin/:id', updateAdminCategory);
router.delete('/admin/:id', deleteAdminCategory);
router.get('/:id', getCategoryById);
router.put('/:id', updateCategory);
router.delete('/:id', deleteCategory);

module.exports = router;
