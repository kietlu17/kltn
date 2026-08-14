const Wallet = require('./Wallet');
const WalletBalance = require('./WalletBalance');
const WalletLedgerEntry = require('./WalletLedgerEntry');
const Account = require('./Account');
const AccountBalance = require('./AccountBalance');
const LedgerTransaction = require('./LedgerTransaction');
const LedgerEntry = require('./LedgerEntry');
const PayoutRequest = require('./PayoutRequest');
const SettlementJob = require('./SettlementJob');
const UserWithdrawalRequest = require('./UserWithdrawalRequest');
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

Account.hasOne(AccountBalance, {
  foreignKey: 'account_id',
  sourceKey: 'id',
  onDelete: 'CASCADE'
});
AccountBalance.belongsTo(Account, {
  foreignKey: 'account_id',
  targetKey: 'id'
});

LedgerTransaction.hasMany(LedgerEntry, {
  foreignKey: 'transaction_id',
  sourceKey: 'id',
  onDelete: 'CASCADE'
});
LedgerEntry.belongsTo(LedgerTransaction, {
  foreignKey: 'transaction_id',
  targetKey: 'id'
});

Account.hasMany(LedgerEntry, {
  foreignKey: 'account_id',
  sourceKey: 'id'
});
LedgerEntry.belongsTo(Account, {
  foreignKey: 'account_id',
  targetKey: 'id'
});

Account.hasMany(PayoutRequest, {
  foreignKey: 'account_id',
  sourceKey: 'id'
});
PayoutRequest.belongsTo(Account, {
  foreignKey: 'account_id',
  targetKey: 'id'
});

Account.hasMany(UserWithdrawalRequest, {
  foreignKey: 'account_id',
  sourceKey: 'id'
});
UserWithdrawalRequest.belongsTo(Account, {
  foreignKey: 'account_id',
  targetKey: 'id'
});

module.exports = {
  Wallet,
  WalletBalance,
  WalletLedgerEntry,
  Account,
  AccountBalance,
  LedgerTransaction,
  LedgerEntry,
  PayoutRequest,
  SettlementJob,
  UserWithdrawalRequest,
  InboxEvent,
  OutboxEvent
};
