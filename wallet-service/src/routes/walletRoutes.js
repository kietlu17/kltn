const express = require('express');
const {
  getWalletByUser,
  topup,
  getWalletTransactions,
  getShopFinanceBalance,
  getShopFinanceLedger,
  settleShopOrder,
  withdrawShopBalance,
  completeShopPayout,
  failShopPayout,
  getShopPayouts
} = require('../controllers/walletController');

const router = express.Router();

router.get('/shop/:shopId/balance', getShopFinanceBalance);
router.get('/shop/:shopId/ledger', getShopFinanceLedger);
router.post('/shop/:shopId/settlements', settleShopOrder);
router.post('/shop/:shopId/withdrawals', withdrawShopBalance);
router.get('/shop/:shopId/payouts', getShopPayouts);
router.post('/payouts/:referenceId/complete', completeShopPayout);
router.post('/payouts/:referenceId/fail', failShopPayout);
router.get('/:userId', getWalletByUser);
router.post('/:userId/topup', topup);
router.get('/:userId/transactions', getWalletTransactions);

module.exports = router;
