const { Sequelize } = require('sequelize');

const sequelize = new Sequelize(
  process.env.PG_DATABASE || 'order_service',
  process.env.PG_USER || 'postgres',
  process.env.PG_PASSWORD || 'postgres',
  {
    host: process.env.PG_HOST || 'localhost',
    port: process.env.PG_PORT ? Number(process.env.PG_PORT) : 5433,
    dialect: 'postgres',
    logging: false
  }
);

async function initDb() {
  await sequelize.authenticate();
  const queryInterface = sequelize.getQueryInterface();

  try {
    const table = await queryInterface.describeTable('orders');
    if (!table.idempotency_key) {
      await queryInterface.addColumn('orders', 'idempotency_key', {
        type: Sequelize.STRING(128),
        allowNull: true
      });
    }
    if (!table.idempotency_request_hash) {
      await queryInterface.addColumn('orders', 'idempotency_request_hash', {
        type: Sequelize.STRING(64),
        allowNull: true
      });
    }

    const indexes = await queryInterface.showIndex('orders');
    const hasUniqueIdempotencyIndex = indexes.some((index) => {
      const fields = (index.fields || []).map((field) => field.attribute || field.name);
      return index.unique && fields.length === 1 && fields[0] === 'idempotency_key';
    });
    if (!hasUniqueIdempotencyIndex) {
      await queryInterface.addIndex('orders', ['idempotency_key'], {
        unique: true,
        name: 'orders_idempotency_key_unique'
      });
    }
  } catch {
    // orders table may not exist yet on first boot; sequelize.sync will create it
  }

  await sequelize.sync();
  console.log('Order Service connected to PostgreSQL');
}

module.exports = { sequelize, initDb };
