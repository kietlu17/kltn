const express = require('express');
const {
  listVouchers,
  listCheckoutVouchers,
  createVoucher,
  updateVoucher,
  reserveVoucher,
  releaseVoucher,
  commitVoucher
} = require('../controllers/voucherController');

const router = express.Router();

router.get('/', listVouchers);
router.post('/checkout', listCheckoutVouchers);
router.post('/', createVoucher);
router.put('/:id', updateVoucher);
router.post('/reserve', reserveVoucher);
router.post('/release', releaseVoucher);
router.post('/commit', commitVoucher);

module.exports = router;
