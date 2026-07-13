const { Sequelize } = require('sequelize');

const databaseName = process.env.PG_DATABASE || 'wallet_service';
const dbUser = process.env.PG_USER || 'postgres';
const dbPassword = process.env.PG_PASSWORD || 'postgres';
const dbHost = process.env.PG_HOST || 'localhost';
const dbPort = process.env.PG_PORT ? Number(process.env.PG_PORT) : 5432;

const sequelize = new Sequelize(
  databaseName,
  dbUser,
  dbPassword,
  {
    host: dbHost,
    port: dbPort,
    dialect: 'postgres',
    logging: false
  }
);

function assertSafeDatabaseName(name) {
  if (!/^[a-zA-Z0-9_-]+$/.test(name)) {
    throw new Error(`Unsafe database name: ${name}`);
  }
}

async function ensureDatabase() {
  assertSafeDatabaseName(databaseName);
  const admin = new Sequelize(
    process.env.PG_ADMIN_DATABASE || 'postgres',
    dbUser,
    dbPassword,
    {
      host: dbHost,
      port: dbPort,
      dialect: 'postgres',
      logging: false
    }
  );

  try {
    const escapedName = databaseName.replace(/"/g, '""');
    await admin.query(`CREATE DATABASE "${escapedName}"`);
    console.log(`Created PostgreSQL database ${databaseName}`);
  } catch (err) {
    if (err?.original?.code !== '42P04' && err?.parent?.code !== '42P04') {
      throw err;
    }
  } finally {
    await admin.close();
  }
}

async function initDb() {
  await ensureDatabase();
  await sequelize.authenticate();
  await sequelize.sync();
  console.log('Wallet Service connected to PostgreSQL');
}

module.exports = { sequelize, initDb };
