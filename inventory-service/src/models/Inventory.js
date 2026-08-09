const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const Inventory = sequelize.define(
  'Inventory',
  {
    id: { type: DataTypes.INTEGER, primaryKey: true, autoIncrement: true },
    product_id: { type: DataTypes.STRING(64), allowNull: false },
    variant_id: { type: DataTypes.STRING(64), allowNull: false, defaultValue: '' },
    shop_id: { type: DataTypes.STRING(64), allowNull: true },
    sku: { type: DataTypes.STRING(120), allowNull: true },
    stock_on_hand: { type: DataTypes.INTEGER, allowNull: false, defaultValue: 0 },
    reserved_stock: { type: DataTypes.INTEGER, allowNull: false, defaultValue: 0 },
    created_at: { type: DataTypes.DATE, allowNull: false, defaultValue: DataTypes.NOW },
    updated_at: { type: DataTypes.DATE, allowNull: false, defaultValue: DataTypes.NOW }
  },
  {
    tableName: 'inventory',
    timestamps: false,
    indexes: [
      {
        unique: true,
        fields: ['product_id', 'variant_id']
      }
    ]
  }
);

module.exports = Inventory;
