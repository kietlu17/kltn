const authService = require("../services/auth.service");

async function register(req, res) {
  try {
    const { email, password } = req.body;
    const user = await authService.register(email, password);
    res.status(201).json(user);
  } catch (err) {
    res.status(400).json({ message: err.message });
  }
}

async function login(req, res) {
  try {
    const { email, password } = req.body;
    const token = await authService.login(email, password);
    res.json(token);
  } catch (err) {
    res.status(401).json({ message: err.message });
  }
}

module.exports = { register, login };
