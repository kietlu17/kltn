const { Sequelize } = require('sequelize');

const sequelize = new Sequelize(
  process.env.PG_DATABASE || 'payment_service',
  process.env.PG_USER || 'postgres',
  process.env.PG_PASSWORD || 'postgres',
  {
    host: process.env.PG_HOST || 'localhost',
    port: process.env.PG_PORT ? Number(process.env.PG_PORT) : 5432,
    dialect: 'postgres',
    logging: false
  }
);

async function initDb() {
  await sequelize.authenticate();
  await sequelize.sync();
  console.log('Payment Service connected to PostgreSQL');
}

module.exports = { sequelize, initDb };
