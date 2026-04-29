const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const Inventory = sequelize.define(
  'Inventory',
  {
    id: { type: DataTypes.INTEGER, primaryKey: true, autoIncrement: true },
    product_id: { type: DataTypes.STRING(64), allowNull: false, unique: true },
    stock: { type: DataTypes.INTEGER, allowNull: false, defaultValue: 0 },
    reserved_stock: { type: DataTypes.INTEGER, allowNull: false, defaultValue: 0 },
    created_at: { type: DataTypes.DATE, allowNull: false, defaultValue: DataTypes.NOW }
  },
  {
    tableName: 'inventory',
    timestamps: false
  }
);

module.exports = Inventory;
