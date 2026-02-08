const bcrypt = require("bcrypt");
const User = require("../models/user.model");
const { signToken } = require("../utils/jwt");

async function register(email, password) {
  const passwordHash = await bcrypt.hash(password, 10);

  const user = await User.create({
    email,
    passwordHash
  });

  return {
    id: user.id,
    email: user.email,
    createdAt: user.created_at
  };
}

async function login(email, password) {
  const user = await User.findOne({ where: { email } });
  if (!user) throw new Error("Invalid credentials");

  const match = await bcrypt.compare(password, user.passwordHash);
  if (!match) throw new Error("Invalid credentials");

  const token = signToken({
    sub: user.id,
    email: user.email
  });

  return { accessToken: token };
}

module.exports = { register, login };
