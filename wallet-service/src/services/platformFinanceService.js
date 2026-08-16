const { sequelize } = require('../config/db');
const {
  getSystemAccount,
  getAccountSnapshot,
  transfer,
  toMoney
} = require('./accountLedgerService');

const PLATFORM_INITIAL_CAPITAL = toMoney(process.env.PLATFORM_INITIAL_CAPITAL || 100000000);

async function ensurePlatformCapital(transaction) {
  const capitalAccount = await getSystemAccount('platform_capital', transaction);
  if (PLATFORM_INITIAL_CAPITAL <= 0) return capitalAccount;

  const externalAccount = await getSystemAccount('external_bank', transaction);
  await transfer({
    fromAccount: externalAccount,
    toAccount: capitalAccount,
    amount: PLATFORM_INITIAL_CAPITAL,
    referenceId: 'ledger:platform:capital:initial',
    idempotencyKey: 'ledger:platform:capital:initial',
    type: 'platform_initial_capital',
    metadata: {
      source: 'paid_in_capital',
      note: 'Initial platform capital for marketplace operations'
    },
    transaction
  });

  return capitalAccount;
}

async function fundPlatformClearingFromCapital({
  amount,
  orderId,
  userId,
  reason,
  sagaId,
  correlationId,
  transaction
}) {
  const fundingAmount = toMoney(amount);
  if (fundingAmount <= 0) return { funded: false, amount: 0 };

  const capitalAccount = await ensurePlatformCapital(transaction);
  const clearingAccount = await getSystemAccount('platform_clearing', transaction);

  const result = await transfer({
    fromAccount: capitalAccount,
    toAccount: clearingAccount,
    amount: fundingAmount,
    referenceId: `ledger:order:${orderId}:refund_capital_advance`,
    idempotencyKey: `ledger:order:${orderId}:refund_capital_advance`,
    type: 'platform_refund_advance',
    metadata: {
      orderId,
      userId,
      reason: reason || 'order_cancelled',
      source: 'platform_capital',
      target: 'platform_clearing'
    },
    sagaId,
    correlationId,
    transaction
  });

  return { funded: true, amount: fundingAmount, reused: result.reused };
}

async function getPlatformWallet() {
  return sequelize.transaction(async (transaction) => {
    const capitalAccount = await ensurePlatformCapital(transaction);
    const clearingAccount = await getSystemAccount('platform_clearing', transaction);
    const capital = await getAccountSnapshot(capitalAccount, transaction);
    const clearing = await getAccountSnapshot(clearingAccount, transaction);

    return {
      currency: capital.currency || clearing.currency || 'VND',
      initialCapital: PLATFORM_INITIAL_CAPITAL,
      capital,
      clearing,
      operatingCapitalAvailable: capital.availableBalance,
      clearingHeldAmount: clearing.availableBalance,
      updatedAt: new Date().toISOString()
    };
  });
}

module.exports = {
  ensurePlatformCapital,
  fundPlatformClearingFromCapital,
  getPlatformWallet
};
