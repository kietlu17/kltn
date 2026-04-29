const express = require('express');
const {
  getWalletByUser,
  topup,
  getWalletTransactions
} = require('../controllers/walletController');

const router = express.Router();

router.get('/wallet/:userId', getWalletByUser);
router.post('/wallet/:userId/topup', topup);
router.get('/wallet/:userId/transactions', getWalletTransactions);

module.exports = router;
