const express = require('express');
const {
  getWalletByUser,
  topup,
  getWalletTransactions,
  createSepayTopupQr,
  createSepayOrderQr,
  getSepayRequestStatus,
  receiveSepayWebhook
} = require('../controllers/walletController');

const router = express.Router();

router.get('/wallet/:userId', getWalletByUser);
router.post('/wallet/:userId/topup', topup);
router.post('/wallet/:userId/topup/sepay-qr', createSepayTopupQr);
router.get('/wallet/:userId/transactions', getWalletTransactions);
router.post('/sepay/orders/:orderId/qr', createSepayOrderQr);
router.get('/sepay/requests/:id', getSepayRequestStatus);
router.post('/sepay/webhook', receiveSepayWebhook);

module.exports = router;
