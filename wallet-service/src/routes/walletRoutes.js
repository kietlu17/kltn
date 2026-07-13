const express = require('express');
const { getWalletByUser, topup, getWalletTransactions } = require('../controllers/walletController');

const router = express.Router();

router.get('/:userId', getWalletByUser);
router.post('/:userId/topup', topup);
router.get('/:userId/transactions', getWalletTransactions);

module.exports = router;
