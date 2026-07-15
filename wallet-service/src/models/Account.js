const { DataTypes } = require('sequelize');
const { sequelize } = require('../config/db');

const Account = sequelize.define(
  'Account',
  {
    id: { type: DataTypes.UUID, primaryKey: true, defaultValue: DataTypes.UUIDV4 },
    owner_type: { type: DataTypes.STRING(24), allowNull: false },
    owner_id: { type: DataTypes.STRING(96), allowNull: false },
    account_type: { type: DataTypes.STRING(40), allowNull: false },
    currency: { type: DataTypes.STRING(8), allowNull: false, defaultValue: 'VND' },
    status: { type: DataTypes.STRING(24), allowNull: false, defaultValue: 'active' },
    allow_negative: { type: DataTypes.BOOLEAN, allowNull: false, defaultValue: false },
    metadata: { type: DataTypes.JSONB, allowNull: false, defaultValue: {} }
  },
  {
    tableName: 'accounts',
    timestamps: true,
    createdAt: 'created_at',
    updatedAt: 'updated_at',
    indexes: [
      { unique: true, fields: ['owner_type', 'owner_id', 'account_type', 'currency'] },
      { fields: ['owner_type', 'owner_id'] },
      { fields: ['account_type'] }
    ]
  }
);

module.exports = Account;
