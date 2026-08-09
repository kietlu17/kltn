const { Sequelize } = require('sequelize');

const databaseName = process.env.PG_DATABASE || 'voucher_service';
const databaseUser = process.env.PG_USER || 'postgres';
const databasePassword = process.env.PG_PASSWORD || 'postgres';
const databaseHost = process.env.PG_HOST || 'localhost';
const databasePort = process.env.PG_PORT ? Number(process.env.PG_PORT) : 5432;

const sequelize = new Sequelize(
  databaseName,
  databaseUser,
  databasePassword,
  {
    host: databaseHost,
    port: databasePort,
    dialect: 'postgres',
    logging: false
  }
);

function quoteIdentifier(value) {
  return `"${String(value).replace(/"/g, '""')}"`;
}

async function ensureDatabaseExists() {
  const admin = new Sequelize('postgres', databaseUser, databasePassword, {
    host: databaseHost,
    port: databasePort,
    dialect: 'postgres',
    logging: false
  });
  try {
    await admin.authenticate();
    const [rows] = await admin.query('SELECT 1 FROM pg_database WHERE datname = :databaseName', {
      replacements: { databaseName }
    });
    if (rows.length === 0) {
      await admin.query(`CREATE DATABASE ${quoteIdentifier(databaseName)}`);
    }
  } finally {
    await admin.close();
  }
}

async function initDb() {
  await ensureDatabaseExists();
  await sequelize.authenticate();
  await sequelize.sync({ alter: true });
  console.log('Voucher Service connected to PostgreSQL');
}

module.exports = { sequelize, initDb };
