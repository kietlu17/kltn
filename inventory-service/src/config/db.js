const { Sequelize } = require('sequelize');

const sequelize = new Sequelize(
  process.env.PG_DATABASE || 'inventory_service',
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
  await migrateLegacyInventoryShape();
  await sequelize.sync({ alter: true });
  await migrateLegacyInventoryShape();
  console.log('Inventory Service connected to PostgreSQL');
}

async function migrateLegacyInventoryShape() {
  const [[table]] = await sequelize.query("SELECT to_regclass('public.inventory') AS name");
  if (!table?.name) return;

  await sequelize.query("ALTER TABLE inventory ADD COLUMN IF NOT EXISTS variant_id VARCHAR(64) DEFAULT ''");
  await sequelize.query("UPDATE inventory SET variant_id = '' WHERE variant_id IS NULL");
  await sequelize.query("ALTER TABLE inventory ALTER COLUMN variant_id SET DEFAULT ''");
  await sequelize.query("ALTER TABLE inventory ALTER COLUMN variant_id SET NOT NULL");
  await sequelize.query('ALTER TABLE inventory ADD COLUMN IF NOT EXISTS shop_id VARCHAR(64)');
  await sequelize.query('ALTER TABLE inventory ADD COLUMN IF NOT EXISTS sku VARCHAR(120)');
  await sequelize.query('ALTER TABLE inventory ADD COLUMN IF NOT EXISTS stock_on_hand INTEGER DEFAULT 0 NOT NULL');
  await sequelize.query('ALTER TABLE inventory ADD COLUMN IF NOT EXISTS reserved_stock INTEGER DEFAULT 0 NOT NULL');
  await sequelize.query('ALTER TABLE inventory ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL');
  await sequelize.query('ALTER TABLE inventory ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL');
  await sequelize.query('UPDATE inventory SET stock_on_hand = 0 WHERE stock_on_hand IS NULL');
  await sequelize.query('UPDATE inventory SET reserved_stock = 0 WHERE reserved_stock IS NULL');
  await sequelize.query('UPDATE inventory SET created_at = NOW() WHERE created_at IS NULL');
  await sequelize.query('UPDATE inventory SET updated_at = NOW() WHERE updated_at IS NULL');
  await sequelize.query('ALTER TABLE inventory ALTER COLUMN stock_on_hand SET DEFAULT 0');
  await sequelize.query('ALTER TABLE inventory ALTER COLUMN stock_on_hand SET NOT NULL');
  await sequelize.query('ALTER TABLE inventory ALTER COLUMN reserved_stock SET DEFAULT 0');
  await sequelize.query('ALTER TABLE inventory ALTER COLUMN reserved_stock SET NOT NULL');
  await sequelize.query('ALTER TABLE inventory ALTER COLUMN created_at SET DEFAULT NOW()');
  await sequelize.query('ALTER TABLE inventory ALTER COLUMN created_at SET NOT NULL');
  await sequelize.query('ALTER TABLE inventory ALTER COLUMN updated_at SET DEFAULT NOW()');
  await sequelize.query('ALTER TABLE inventory ALTER COLUMN updated_at SET NOT NULL');

  const [columns] = await sequelize.query(`
    SELECT column_name
    FROM information_schema.columns
    WHERE table_name = 'inventory'
      AND column_name IN ('stock', 'stock_on_hand', 'reserved_stock')
  `);
  const names = new Set(columns.map((row) => row.column_name));
  if (names.has('stock') && names.has('stock_on_hand')) {
    await sequelize.query(`
      UPDATE inventory
      SET stock_on_hand = GREATEST(stock_on_hand, stock, reserved_stock)
      WHERE stock IS NOT NULL
    `);
  }
  await sequelize.query("UPDATE inventory SET variant_id = '' WHERE variant_id IS NULL");
  await sequelize.query('ALTER TABLE inventory DROP CONSTRAINT IF EXISTS inventory_product_id_key');
  await sequelize.query(`
    CREATE UNIQUE INDEX IF NOT EXISTS inventory_product_variant_unique
    ON inventory (product_id, variant_id)
  `);
}

module.exports = { sequelize, initDb };
