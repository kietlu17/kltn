const Wallet = require('./Wallet');
const WalletTransaction = require('./WalletTransaction');

Wallet.hasMany(WalletTransaction, {
  foreignKey: 'user_id',
  sourceKey: 'user_id'
});
WalletTransaction.belongsTo(Wallet, {
  foreignKey: 'user_id',
  targetKey: 'user_id'
});

module.exports = {
  Wallet,
  WalletTransaction
};
