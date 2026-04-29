const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const Dispute = sequelize.define(
  'Dispute',
  {
    id: { type: DataTypes.INTEGER, primaryKey: true, autoIncrement: true },
    order_id: { type: DataTypes.INTEGER, allowNull: false },
    user_id: { type: DataTypes.STRING(64), allowNull: false },
    reason: { type: DataTypes.STRING(120), allowNull: false },
    note: { type: DataTypes.TEXT, allowNull: true },
    evidence_text: { type: DataTypes.TEXT, allowNull: true },
    status: { type: DataTypes.STRING(20), allowNull: false, defaultValue: 'open' },
    handled_by: { type: DataTypes.STRING(64), allowNull: true },
    handled_note: { type: DataTypes.TEXT, allowNull: true },
    handled_at: { type: DataTypes.DATE, allowNull: true },
    created_at: { type: DataTypes.DATE, allowNull: false, defaultValue: DataTypes.NOW }
  },
  {
    tableName: 'disputes',
    timestamps: false
  }
);

module.exports = Dispute;
