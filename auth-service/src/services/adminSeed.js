const bcrypt = require('bcryptjs');
const User = require('../models/User');

async function seedAdminUser() {
  const email = (process.env.ADMIN_EMAIL || '').trim();
  const password = process.env.ADMIN_PASSWORD || '';
  if (!email || !password) {
    console.log('Admin seed skipped: ADMIN_EMAIL or ADMIN_PASSWORD not set');
    return;
  }
  const existing = await User.findOne({ email });
  if (existing) {
    let touched = false;
    if (existing.role !== 'admin') {
      existing.role = 'admin';
      touched = true;
    }
    if (!existing.isActive) {
      existing.isActive = true;
      touched = true;
    }
    if (touched) {
      await existing.save();
      console.log('Admin seed updated existing account');
    }
    return;
  }
  const hash = await bcrypt.hash(password, 10);
  await User.create({
    email,
    password: hash,
    role: 'admin',
    shopId: null,
    isActive: true,
    tokenVersion: 0
  });
  console.log('Admin seed created account');
}

module.exports = { seedAdminUser };
