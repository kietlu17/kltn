const express = require('express');
const { getReviewsByProduct, getReviewSummaries, getReviewInsights, createReview } = require('../controllers/reviewController');

const router = express.Router();

router.get('/products/summary', getReviewSummaries);
router.get('/products/insights', getReviewInsights);
router.get('/product/:productId', getReviewsByProduct);
router.post('/product/:productId', createReview);

module.exports = router;
