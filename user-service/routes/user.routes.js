const express = require("express");
const authenticate = require("../middlewares/auth.middleware");
const { getProfile } = require("../controllers/user.controller");

const router = express.Router();

/**
 * Protected endpoint
 */
router.get("/me", authenticate, getProfile);

module.exports = router;
