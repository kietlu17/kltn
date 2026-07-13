const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const OutboxEvent = sequelize.define(
  'OutboxEvent',
  {
    id: { type: DataTypes.UUID, primaryKey: true, defaultValue: DataTypes.UUIDV4 },
    aggregate_type: { type: DataTypes.STRING(80), allowNull: false },
    aggregate_id: { type: DataTypes.STRING(128), allowNull: false },
    event_type: { type: DataTypes.STRING(120), allowNull: false },
    topic: { type: DataTypes.STRING(120), allowNull: false },
    event_key: { type: DataTypes.STRING(128), allowNull: false },
    payload: { type: DataTypes.JSONB, allowNull: false, defaultValue: {} },
    headers: { type: DataTypes.JSONB, allowNull: false, defaultValue: {} },
    status: { type: DataTypes.STRING(24), allowNull: false, defaultValue: 'pending' },
    attempts: { type: DataTypes.INTEGER, allowNull: false, defaultValue: 0 },
    next_attempt_at: { type: DataTypes.DATE, allowNull: true },
    published_at: { type: DataTypes.DATE, allowNull: true },
    error: { type: DataTypes.TEXT, allowNull: true },
    saga_id: { type: DataTypes.STRING(128), allowNull: true },
    correlation_id: { type: DataTypes.STRING(128), allowNull: true }
  },
  {
    tableName: 'outbox_events',
    timestamps: true,
    createdAt: 'created_at',
    updatedAt: 'updated_at',
    indexes: [{ fields: ['status', 'next_attempt_at'] }]
  }
);

module.exports = OutboxEvent;
