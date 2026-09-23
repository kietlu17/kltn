const express = require('express');
const { getReviewsByProduct, getReviewSummaries, createReview } = require('../controllers/reviewController');

const router = express.Router();

router.get('/products/summary', getReviewSummaries);
router.get('/product/:productId', getReviewsByProduct);
router.post('/product/:productId', createReview);

module.exports = router;
