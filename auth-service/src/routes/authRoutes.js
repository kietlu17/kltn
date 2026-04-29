const express = require('express');
const {
  register,
  login,
  validateSession,
  validateToken,
  getAdminUsers,
  lockUser,
  unlockUser
} = require('../controllers/authController');
const { requireAdmin } = require('../middleware/requireAdmin');

const router = express.Router();

router.post('/register', register);
router.post('/login', login);
router.get('/validate', validateSession);
router.post('/session', validateToken);
router.get('/admin/users', requireAdmin, getAdminUsers);
router.patch('/admin/users/:id/lock', requireAdmin, lockUser);
router.patch('/admin/users/:id/unlock', requireAdmin, unlockUser);

module.exports = router;
