const express = require('express');
const {
  createUser,
  getUsers,
  getUserById,
  updateUser,
  getAddresses,
  addAddress,
  updateAddress,
  deleteAddress,
  setDefaultAddress
} = require('../controllers/userController');

const router = express.Router();

router.post('/', createUser);
router.get('/', getUsers);
router.get('/:id', getUserById);
router.put('/:id', updateUser);
router.get('/:id/addresses', getAddresses);
router.post('/:id/addresses', addAddress);
router.put('/:id/addresses/:addressId', updateAddress);
router.delete('/:id/addresses/:addressId', deleteAddress);
router.put('/:id/addresses/:addressId/default', setDefaultAddress);

module.exports = router;
