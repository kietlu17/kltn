const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const InboxEvent = sequelize.define(
  'InboxEvent',
  {
    id: { type: DataTypes.INTEGER, primaryKey: true, autoIncrement: true },
    message_id: { type: DataTypes.STRING(160), allowNull: false, unique: true },
    topic: { type: DataTypes.STRING(120), allowNull: false },
    payload: { type: DataTypes.JSONB, allowNull: false, defaultValue: {} },
    status: { type: DataTypes.STRING(24), allowNull: false, defaultValue: 'processing' },
    attempts: { type: DataTypes.INTEGER, allowNull: false, defaultValue: 0 },
    error: { type: DataTypes.TEXT, allowNull: true },
    processed_at: { type: DataTypes.DATE, allowNull: true }
  },
  {
    tableName: 'inbox_events',
    timestamps: true,
    createdAt: 'created_at',
    updatedAt: 'updated_at'
  }
);

module.exports = InboxEvent;
