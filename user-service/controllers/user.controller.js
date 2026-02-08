const User = require("../models/user.model");

async function getProfile(req, res) {
  const userId = req.user.id;

  const user = await User.findByPk(userId);

  if (!user)
    return res.status(404).json({ message: "User not found" });

  res.json(user);
}

module.exports = { getProfile };
