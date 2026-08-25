const express = require('express');
const {
  createShop,
  getShops,
  getShopById,
  getInvoiceFeature,
  createInvoiceFeatureRequest,
  getAdminInvoiceFeatureRequests,
  reviewInvoiceFeatureRequest
} = require('../controllers/shopController');

const router = express.Router();

router.post('/', createShop);
router.get('/', getShops);
router.get('/admin/invoice-feature-requests', getAdminInvoiceFeatureRequests);
router.patch('/admin/invoice-feature-requests/:requestId', reviewInvoiceFeatureRequest);
router.get('/:id/invoice-feature', getInvoiceFeature);
router.post('/:id/invoice-feature-requests', createInvoiceFeatureRequest);
router.get('/:id', getShopById);

module.exports = router;
