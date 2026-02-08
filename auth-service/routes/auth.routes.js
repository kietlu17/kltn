const express = require("express");
const router = express.Router();
const controller = require("../controllers/auth.controller");
const authGuard = require("../middlewares/auth.middleware");

router.post("/register", controller.register);
router.post("/login", controller.login);

router.get("/me", authGuard, (req, res) => {
  res.json(req.user);
});

module.exports = router;
