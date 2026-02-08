const jwt = require("jsonwebtoken");

function verifyToken(token) {
  return jwt.verify(token, process.env.JWT_PUBLIC_KEY, {
    issuer: process.env.JWT_ISSUER
  });
}

module.exports = { verifyToken };
