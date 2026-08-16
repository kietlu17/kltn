const express = require('express');
const {
  getWalletByUser,
  topup,
  getWalletTransactions,
  getPlatformFinanceWallet,
  getShopFinanceBalance,
  getShopFinanceLedger,
  settleShopOrder,
  withdrawShopBalance,
  completeShopPayout,
  failShopPayout,
  getShopPayouts,
  getSettlementJobs,
  runSettlements,
  receiveCodRemittance,
  withdrawUserBalance,
  getUserWithdrawals,
  completeUserWithdrawalRequest,
  failUserWithdrawalRequest
} = require('../controllers/walletController');

const router = express.Router();

router.get('/platform-wallet', getPlatformFinanceWallet);
router.get('/shop/:shopId/balance', getShopFinanceBalance);
router.get('/shop/:shopId/ledger', getShopFinanceLedger);
router.post('/shop/:shopId/settlements', settleShopOrder);
router.post('/shop/:shopId/withdrawals', withdrawShopBalance);
router.get('/shop/:shopId/payouts', getShopPayouts);
router.get('/settlements', getSettlementJobs);
router.post('/settlements/run', runSettlements);
router.post('/cod-remittances', receiveCodRemittance);
router.post('/payouts/:referenceId/complete', completeShopPayout);
router.post('/payouts/:referenceId/fail', failShopPayout);
router.post('/user-withdrawals/:referenceId/complete', completeUserWithdrawalRequest);
router.post('/user-withdrawals/:referenceId/fail', failUserWithdrawalRequest);
router.get('/:userId', getWalletByUser);
router.post('/:userId/topup', topup);
router.get('/:userId/transactions', getWalletTransactions);
router.post('/:userId/withdrawals', withdrawUserBalance);
router.get('/:userId/withdrawals', getUserWithdrawals);

module.exports = router;
