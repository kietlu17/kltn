const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const Shipment = sequelize.define(
  'Shipment',
  {
    id: { type: DataTypes.INTEGER, primaryKey: true, autoIncrement: true },
    order_id: { type: DataTypes.INTEGER, allowNull: false },
    shop_id: { type: DataTypes.STRING(64), allowNull: false },
    tracking_code: { type: DataTypes.STRING(64), allowNull: false, unique: true },
    carrier: { type: DataTypes.STRING(80), allowNull: false, defaultValue: 'mock_carrier' },
    status: { type: DataTypes.STRING(32), allowNull: false, defaultValue: 'requested' },
    callback_url: { type: DataTypes.STRING(240), allowNull: true },
    metadata: { type: DataTypes.JSONB, allowNull: false, defaultValue: {} },
    handed_over_at: { type: DataTypes.DATE, allowNull: true },
    in_transit_at: { type: DataTypes.DATE, allowNull: true },
    delivered_at: { type: DataTypes.DATE, allowNull: true },
    created_at: { type: DataTypes.DATE, allowNull: false, defaultValue: DataTypes.NOW },
    updated_at: { type: DataTypes.DATE, allowNull: false, defaultValue: DataTypes.NOW }
  },
  {
    tableName: 'shipments',
    timestamps: false,
    indexes: [
      { fields: ['order_id'] },
      { fields: ['shop_id'] },
      { fields: ['status'] }
    ]
  }
);

module.exports = Shipment;
