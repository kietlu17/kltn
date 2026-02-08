const { verifyToken } = require("../utils/jwt");

function authGuard(req, res, next) {
  const authHeader = req.headers.authorization;
  if (!authHeader) return res.sendStatus(401);

  const token = authHeader.split(" ")[1];

  try {
    req.user = verifyToken(token);
    next();
  } catch {
    res.sendStatus(403);
  }
}

module.exports = authGuard;
