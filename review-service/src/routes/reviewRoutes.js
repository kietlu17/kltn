const express = require('express');
const { getReviewsByProduct, createReview } = require('../controllers/reviewController');

const router = express.Router();

router.get('/product/:productId', getReviewsByProduct);
router.post('/product/:productId', createReview);

module.exports = router;
