const Wallet = require('./Wallet');
const WalletBalance = require('./WalletBalance');
const WalletLedgerEntry = require('./WalletLedgerEntry');
const InboxEvent = require('./InboxEvent');
const OutboxEvent = require('./OutboxEvent');

Wallet.hasOne(WalletBalance, {
  foreignKey: 'wallet_id',
  sourceKey: 'id',
  onDelete: 'CASCADE'
});
WalletBalance.belongsTo(Wallet, {
  foreignKey: 'wallet_id',
  targetKey: 'id'
});

Wallet.hasMany(WalletLedgerEntry, {
  foreignKey: 'wallet_id',
  sourceKey: 'id'
});
WalletLedgerEntry.belongsTo(Wallet, {
  foreignKey: 'wallet_id',
  targetKey: 'id'
});

module.exports = {
  Wallet,
  WalletBalance,
  WalletLedgerEntry,
  InboxEvent,
  OutboxEvent
};
