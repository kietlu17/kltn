const UserProfile = require('../models/UserProfile');

async function createUser(req, res) {
  try {
    const { userId, name, address, phone } = req.body;
    if (!userId) {
      return res.status(400).json({ message: 'userId is required' });
    }
    const existing = await UserProfile.findOne({ userId });
    if (existing) {
      return res.status(409).json({ message: 'User profile already exists' });
    }
    const user = await UserProfile.create({ userId, name, address, phone });
    return res.status(201).json(user);
  } catch (err) {
    return res.status(500).json({ message: 'Create user failed', error: err.message });
  }
}

async function getUsers(req, res) {
  try {
    const users = await UserProfile.find();
    return res.json(users);
  } catch (err) {
    return res.status(500).json({ message: 'Get users failed', error: err.message });
  }
}

async function getUserById(req, res) {
  try {
    const user = await UserProfile.findOne({ userId: req.params.id });
    if (!user) {
      return res.status(404).json({ message: 'User not found' });
    }
    return res.json(user);
  } catch (err) {
    return res.status(500).json({ message: 'Get user failed', error: err.message });
  }
}

async function updateUser(req, res) {
  try {
    const user = await UserProfile.findOne({ userId: req.params.id });
    if (!user) {
      return res.status(404).json({ message: 'User not found' });
    }
    const { name } = req.body || {};
    if (typeof name === 'string') {
      if (!name.trim()) {
        return res.status(400).json({ message: 'name is required' });
      }
      user.name = name.trim();
    }
    await user.save();
    return res.json(user);
  } catch (err) {
    return res.status(500).json({ message: 'Update user failed', error: err.message });
  }
}

async function getAddresses(req, res) {
  try {
    const user = await UserProfile.findOne({ userId: req.params.id });
    if (!user) {
      return res.status(404).json({ message: 'User not found' });
    }
    return res.json(user.addresses || []);
  } catch (err) {
    return res.status(500).json({ message: 'Get addresses failed', error: err.message });
  }
}

async function addAddress(req, res) {
  try {
    const user = await UserProfile.findOne({ userId: req.params.id });
    if (!user) {
      return res.status(404).json({ message: 'User not found' });
    }
    const address = req.body;
    if (!address || !address.line1) {
      return res.status(400).json({ message: 'Address line1 is required' });
    }
    const nextAddress = {
      label: address.label || '',
      fullName: address.fullName || '',
      phone: address.phone || '',
      line1: address.line1 || '',
      line2: address.line2 || '',
      city: address.city || '',
      state: address.state || '',
      postalCode: address.postalCode || '',
      country: address.country || '',
      isDefault: Boolean(address.isDefault)
    };
    if (!user.addresses) user.addresses = [];
    if (nextAddress.isDefault) {
      user.addresses.forEach((item) => {
        item.isDefault = false;
      });
    }
    user.addresses.push(nextAddress);
    await user.save();
    return res.status(201).json(user.addresses);
  } catch (err) {
    return res.status(500).json({ message: 'Add address failed', error: err.message });
  }
}

async function updateAddress(req, res) {
  try {
    const user = await UserProfile.findOne({ userId: req.params.id });
    if (!user) {
      return res.status(404).json({ message: 'User not found' });
    }
    const address = user.addresses.id(req.params.addressId);
    if (!address) {
      return res.status(404).json({ message: 'Address not found' });
    }
    const updates = req.body || {};
    Object.keys(updates).forEach((key) => {
      if (key in address) address[key] = updates[key];
    });
    if (updates.isDefault === true) {
      user.addresses.forEach((item) => {
        item.isDefault = item._id.toString() === address._id.toString();
      });
    }
    await user.save();
    return res.json(user.addresses);
  } catch (err) {
    return res.status(500).json({ message: 'Update address failed', error: err.message });
  }
}

async function deleteAddress(req, res) {
  try {
    const user = await UserProfile.findOne({ userId: req.params.id });
    if (!user) {
      return res.status(404).json({ message: 'User not found' });
    }
    const address = user.addresses.id(req.params.addressId);
    if (!address) {
      return res.status(404).json({ message: 'Address not found' });
    }
    address.remove();
    await user.save();
    return res.json(user.addresses);
  } catch (err) {
    return res.status(500).json({ message: 'Delete address failed', error: err.message });
  }
}

async function setDefaultAddress(req, res) {
  try {
    const user = await UserProfile.findOne({ userId: req.params.id });
    if (!user) {
      return res.status(404).json({ message: 'User not found' });
    }
    const address = user.addresses.id(req.params.addressId);
    if (!address) {
      return res.status(404).json({ message: 'Address not found' });
    }
    user.addresses.forEach((item) => {
      item.isDefault = item._id.toString() === address._id.toString();
    });
    await user.save();
    return res.json(user.addresses);
  } catch (err) {
    return res.status(500).json({ message: 'Set default address failed', error: err.message });
  }
}

module.exports = {
  createUser,
  getUsers,
  getUserById,
  updateUser,
  getAddresses,
  addAddress,
  updateAddress,
  deleteAddress,
  setDefaultAddress
};
