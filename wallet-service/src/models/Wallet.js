const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const Wallet = sequelize.define(
  'Wallet',
  {
    id: { type: DataTypes.UUID, primaryKey: true, defaultValue: DataTypes.UUIDV4 },
    user_id: { type: DataTypes.STRING(64), allowNull: false },
    currency: { type: DataTypes.STRING(8), allowNull: false, defaultValue: 'VND' },
    status: { type: DataTypes.STRING(24), allowNull: false, defaultValue: 'active' }
  },
  {
    tableName: 'wallets',
    timestamps: true,
    createdAt: 'created_at',
    updatedAt: 'updated_at',
    indexes: [{ unique: true, fields: ['user_id', 'currency'] }]
  }
);

module.exports = Wallet;
