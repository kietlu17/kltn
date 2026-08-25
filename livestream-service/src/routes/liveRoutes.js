const express = require('express');
const {
  createLive,
  listLives,
  listSellerLives,
  getLive,
  startLive,
  endLive,
  createSellerToken,
  createViewerToken,
  listPinnedProducts,
  pinProduct,
  setActiveProduct,
  unpinProduct,
  handleLivekitWebhook
} = require('../controllers/liveController');

const router = express.Router();

router.post('/provider/livekit/webhook', handleLivekitWebhook);
router.get('/active', listLives);
router.get('/seller/me', listSellerLives);
router.post('/', createLive);
router.get('/', listLives);
router.get('/:liveId', getLive);
router.post('/:liveId/start', startLive);
router.post('/:liveId/end', endLive);
router.post('/:liveId/seller-token', createSellerToken);
router.post('/:liveId/viewer-token', createViewerToken);
router.get('/:liveId/pinned-products', listPinnedProducts);
router.post('/:liveId/pinned-products', pinProduct);
router.patch('/:liveId/active-product', setActiveProduct);
router.delete('/:liveId/pinned-products/:productId', unpinProduct);

module.exports = router;
