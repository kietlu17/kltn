const { verifyToken } = require("../utils/jwt");

function authenticate(req, res, next) {
  const authHeader = req.headers.authorization;

  if (!authHeader)
    return res.status(401).json({ message: "Missing token" });

  const token = authHeader.split(" ")[1];

  try {
    const payload = verifyToken(token);

    /**
     * Zero Trust:
     * - Không tin gateway
     * - Không tin client
     * - Chỉ tin token đã verify
     */
    req.user = {
      id: payload.sub,
      email: payload.email,
      roles: payload.roles || []
    };

    next();
  } catch (err) {
    res.status(401).json({ message: "Invalid or expired token" });
  }
}

module.exports = authenticate;
