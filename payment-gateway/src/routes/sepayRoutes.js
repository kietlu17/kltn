const express = require('express');
const {
  createSepayTopupQr,
  createSepayOrderQr,
  getSepayRequestStatus,
  receiveSepayWebhook
} = require('../controllers/sepayController');

const router = express.Router();

router.post('/wallet/:userId/topup/sepay-qr', createSepayTopupQr);
router.post('/sepay/orders/:orderId/qr', createSepayOrderQr);
router.get('/sepay/requests/:id', getSepayRequestStatus);
router.post('/sepay/webhook', receiveSepayWebhook);

module.exports = router;
