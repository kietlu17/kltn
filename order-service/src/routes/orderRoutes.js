const express = require('express');
const {
  createOrder,
  cancelOrder,
  confirmOrder,
  getUserOrders,
  getSellerOrders,
  getSellerStats,
  getAdminOrders,
  updateAdminOrderStatus,
  forceCancelOrder,
  createDispute,
  getAdminDisputes,
  updateAdminDispute
} = require('../controllers/orderController');

const router = express.Router();

router.post('/', createOrder);
router.post('/:id/cancel', cancelOrder);
router.post('/:id/confirm', confirmOrder);
router.post('/:id/disputes', createDispute);
router.get('/seller/:shopId/stats', getSellerStats);
router.get('/seller/:shopId', getSellerOrders);
router.get('/admin/orders', getAdminOrders);
router.patch('/admin/orders/:id/status', updateAdminOrderStatus);
router.post('/admin/orders/:id/force-cancel', forceCancelOrder);
router.get('/admin/disputes', getAdminDisputes);
router.patch('/admin/disputes/:id', updateAdminDispute);
router.get('/:userId', getUserOrders);

module.exports = router;
