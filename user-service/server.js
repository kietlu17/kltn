const app = require("./app");
const sequelize = require("./config/database");
require("dotenv").config();

(async () => {
  await sequelize.authenticate();
  console.log("User DB connected");

  app.listen(process.env.PORT, () => {
    console.log(`User Service running on ${process.env.PORT}`);
  });
})();
