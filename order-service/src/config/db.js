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
    if (!table.subtotal_price) {
      await queryInterface.addColumn('orders', 'subtotal_price', {
        type: Sequelize.DECIMAL(12, 2),
        allowNull: false,
        defaultValue: 0
      });
    }
    if (!table.discount_amount) {
      await queryInterface.addColumn('orders', 'discount_amount', {
        type: Sequelize.DECIMAL(12, 2),
        allowNull: false,
        defaultValue: 0
      });
    }
    if (!table.voucher_code) {
      await queryInterface.addColumn('orders', 'voucher_code', {
        type: Sequelize.STRING(40),
        allowNull: true
      });
    }
    if (!table.voucher_snapshot) {
      await queryInterface.addColumn('orders', 'voucher_snapshot', {
        type: Sequelize.JSONB,
        allowNull: true
      });
    }
    if (!table.shipment_tracking_code) {
      await queryInterface.addColumn('orders', 'shipment_tracking_code', {
        type: Sequelize.STRING(64),
        allowNull: true
      });
    }
    if (!table.delivered_at) {
      await queryInterface.addColumn('orders', 'delivered_at', {
        type: Sequelize.DATE,
        allowNull: true
      });
    }
    if (!table.settlement_status) {
      await queryInterface.addColumn('orders', 'settlement_status', {
        type: Sequelize.STRING(32),
        allowNull: false,
        defaultValue: 'not_eligible'
      });
    }
    if (!table.settlement_eligible_at) {
      await queryInterface.addColumn('orders', 'settlement_eligible_at', {
        type: Sequelize.DATE,
        allowNull: true
      });
    }
    if (!table.settled_at) {
      await queryInterface.addColumn('orders', 'settled_at', {
        type: Sequelize.DATE,
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
  try {
    await sequelize.query('UPDATE orders SET subtotal_price = total_price WHERE subtotal_price = 0 AND total_price IS NOT NULL');
  } catch {
    // first boot tables are created by sync
  }
  console.log('Order Service connected to PostgreSQL');
}

module.exports = { sequelize, initDb };
