require("dotenv").config();
const app = require("./app");
const sequelize = require("./config/database");

(async () => {
  try {
    await sequelize.authenticate();
    await sequelize.sync(); // MVP: dùng sync, production dùng migration
    console.log("DB connected");

    app.listen(process.env.PORT, () => {
      console.log(`Auth service running on port ${process.env.PORT}`);
    });
  } catch (err) {
    console.error("DB error:", err);
  }
})();
