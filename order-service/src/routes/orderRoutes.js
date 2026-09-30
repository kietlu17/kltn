const express = require('express');
const {
  createOrder,
  cancelOrder,
  confirmOrder,
  getUserOrders,
  getSellerOrders,
  getSellerStats,
  updateInvoiceStatus,
  getAdminOrders,
  updateAdminOrderStatus,
  forceCancelOrder,
  createDispute,
  getAdminDisputes,
  updateAdminDispute,
  createShipment,
  getOrderShipment,
  simulateShipmentStatus,
  receiveShippingCallback
} = require('../controllers/orderController');
const { createCheckoutQuote, confirmCheckout } = require('../controllers/checkoutController');

const router = express.Router();

router.post('/', createOrder);
router.post('/checkout/quotes', createCheckoutQuote);
router.post('/checkout/quotes/:id/confirm', confirmCheckout);
router.post('/:id/cancel', cancelOrder);
router.post('/:id/confirm', confirmOrder);
router.post('/:id/shipments', createShipment);
router.post('/:id/disputes', createDispute);
router.get('/shipments/order/:orderId', getOrderShipment);
router.post('/shipments/:trackingCode/simulate', simulateShipmentStatus);
router.post('/shipping/callback', receiveShippingCallback);
router.get('/user', getUserOrders);
router.get('/seller/:shopId/stats', getSellerStats);
router.get('/seller/:shopId', getSellerOrders);
router.patch('/:id/invoice', updateInvoiceStatus);
router.get('/admin/orders', getAdminOrders);
router.patch('/admin/orders/:id/status', updateAdminOrderStatus);
router.post('/admin/orders/:id/force-cancel', forceCancelOrder);
router.get('/admin/disputes', getAdminDisputes);
router.patch('/admin/disputes/:id', updateAdminDispute);
router.get('/:userId', getUserOrders);

module.exports = router;
