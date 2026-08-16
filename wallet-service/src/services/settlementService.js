const { Op } = require('sequelize');
const { sequelize } = require('../config/db');
const { SettlementJob, OutboxEvent } = require('../models');
const { settleOrderToShop } = require('./shopFinanceService');
const { getSystemAccount, transfer } = require('./accountLedgerService');

const SETTLEMENT_DELAY_DAYS = Number(process.env.SETTLEMENT_DELAY_DAYS || 15);

function toMoney(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Number(number.toFixed(2));
}

function parseOrderItems(payload) {
  if (Array.isArray(payload?.products)) return payload.products;
  if (typeof payload?.products === 'string') {
    try {
      return JSON.parse(payload.products);
    } catch {
      return [];
    }
  }
  return [];
}

function buildEligibleAt(deliveredAt) {
  const base = deliveredAt ? new Date(deliveredAt) : new Date();
  const safeBase = Number.isNaN(base.getTime()) ? new Date() : base;
  return new Date(safeBase.getTime() + SETTLEMENT_DELAY_DAYS * 24 * 60 * 60 * 1000);
}

function getSettlementAmount(payload, shopId) {
  const total = toMoney(payload?.total_price || payload?.totalPrice || payload?.amount);
  if (total > 0) return total;
  return parseOrderItems(payload)
    .filter((item) => String(item?.shopId || '') === String(shopId))
    .reduce((sum, item) => toMoney(sum + Number(item.price || 0) * Number(item.quantity || 0)), 0);
}

async function enqueueSettlementCompleted(transaction, job, ledgerResult) {
  const payload = {
    eventId: `ShopSettlementCompleted:${job.reference_id}`,
    eventType: 'ShopSettlementCompleted',
    orderId: job.order_id,
    shopId: job.shop_id,
    amount: toMoney(job.amount),
    referenceId: job.reference_id,
    ledgerTransactionId: ledgerResult.ledgerTransactionId,
    settledAt: job.settled_at,
    sagaId: job.saga_id || null,
    correlationId: job.correlation_id || null,
    occurredAt: new Date().toISOString()
  };
  await OutboxEvent.create(
    {
      aggregate_type: 'settlement',
      aggregate_id: String(job.order_id),
      event_type: payload.eventType,
      topic: 'shop.settlement.completed',
      event_key: String(job.order_id),
      payload,
      headers: {
        sagaId: payload.sagaId || '',
        correlationId: payload.correlationId || ''
      },
      saga_id: payload.sagaId,
      correlation_id: payload.correlationId
    },
    { transaction }
  );
}

async function createSettlementJobsForDeliveredOrder(payload) {
  const orderId = Number(payload?.id || payload?.orderId);
  if (!Number.isFinite(orderId)) return [];
  const method = String(payload?.payment_method || payload?.paymentMethod || '').toLowerCase();
  if (!['wallet', 'bank_transfer', 'sepay', 'cod'].includes(method)) return [];

  const items = parseOrderItems(payload);
  const shopIds = [...new Set(items.map((item) => item?.shopId).filter(Boolean).map(String))];
  const effectiveShopIds = shopIds.length ? shopIds : [String(payload?.shopId || '')].filter(Boolean);
  if (!effectiveShopIds.length) return [];

  const eligibleAt = payload?.settlement_eligible_at || payload?.settlementEligibleAt || buildEligibleAt(payload?.delivered_at || payload?.deliveredAt);
  const createdJobs = [];
  await sequelize.transaction(async (transaction) => {
    for (const shopId of effectiveShopIds) {
      const amount = getSettlementAmount(payload, shopId);
      if (amount <= 0) continue;
      const referenceId = `order:${orderId}:shop:${shopId}:settlement`;
      const [job] = await SettlementJob.findOrCreate({
        where: { reference_id: referenceId },
        defaults: {
          order_id: orderId,
          shop_id: shopId,
          amount,
          status: method === 'cod' ? 'awaiting_remittance' : 'pending',
          eligible_at: eligibleAt,
          reference_id: referenceId,
          metadata: {
            paymentMethod: method,
            deliveredAt: payload?.delivered_at || payload?.deliveredAt || null,
            remittanceRequired: method === 'cod'
          },
          saga_id: payload?.sagaId || `order:${orderId}:settlement`,
          correlation_id: payload?.correlationId || `order:${orderId}:settlement`
        },
        transaction
      });
      createdJobs.push(job.toJSON());
    }
  });
  return createdJobs;
}

async function settleJob(job) {
  const ledgerResult = await settleOrderToShop({
    shopId: job.shop_id,
    orderId: job.order_id,
    amount: job.amount,
    referenceId: job.reference_id,
    metadata: {
      source: 'settlement_job',
      eligibleAt: job.eligible_at
    },
    sagaId: job.saga_id,
    correlationId: job.correlation_id
  });

  return sequelize.transaction(async (transaction) => {
    const locked = await SettlementJob.findByPk(job.id, {
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    if (!locked || locked.status === 'settled') return null;
    locked.status = 'settled';
    locked.settled_at = new Date();
    locked.metadata = {
      ...(locked.metadata || {}),
      ledgerTransactionId: ledgerResult.ledgerTransactionId
    };
    await locked.save({ transaction });
    await enqueueSettlementCompleted(transaction, locked, ledgerResult);
    return locked.toJSON();
  });
}

async function processDueSettlements({ force = false, limit = 50 } = {}) {
  const where = {
    status: 'pending',
    ...(force ? {} : { eligible_at: { [Op.lte]: new Date() } })
  };
  const jobs = await SettlementJob.findAll({
    where,
    order: [['eligible_at', 'ASC']],
    limit: Math.max(1, Math.min(Number(limit) || 50, 200))
  });

  const results = [];
  for (const job of jobs) {
    const settled = await settleJob(job);
    if (settled) results.push(settled);
  }

  return results;
}

async function recordCodRemittance({
  orderId,
  shopId,
  amount,
  carrier = 'mock_carrier',
  referenceId,
  metadata = {},
  sagaId = null,
  correlationId = null
}) {
  const normalizedOrderId = Number(orderId);
  const remittanceAmount = toMoney(amount);
  if (!Number.isFinite(normalizedOrderId)) throw new Error('orderId is required');
  if (!shopId) throw new Error('shopId is required');
  if (remittanceAmount <= 0) throw new Error('amount must be greater than 0');

  const settlementReference = `order:${normalizedOrderId}:shop:${shopId}:settlement`;
  const job = await SettlementJob.findOne({ where: { reference_id: settlementReference } });
  if (!job) throw new Error('settlement_job_not_found');
  if (job.status === 'settled') return { ok: true, reused: true, job: job.toJSON() };
  if (job.status !== 'awaiting_remittance' && job.status !== 'pending') {
    throw new Error(`settlement_job_not_payable:${job.status}`);
  }

  const expectedAmount = toMoney(job.amount);
  if (remittanceAmount !== expectedAmount) {
    throw new Error(`cod_remittance_amount_mismatch:${remittanceAmount}:${expectedAmount}`);
  }

  await sequelize.transaction(async (transaction) => {
    const externalAccount = await getSystemAccount('external_bank', transaction);
    const platformAccount = await getSystemAccount('platform_clearing', transaction);
    await transfer({
      fromAccount: externalAccount,
      toAccount: platformAccount,
      amount: expectedAmount,
      referenceId: `ledger:order:${normalizedOrderId}:shop:${shopId}:cod_remittance`,
      idempotencyKey: referenceId || `ledger:order:${normalizedOrderId}:shop:${shopId}:cod_remittance`,
      type: 'cod_carrier_remittance',
      metadata: {
        orderId: normalizedOrderId,
        shopId,
        carrier,
        remittedAmount: remittanceAmount,
        expectedAmount,
        ...metadata
      },
      sagaId: sagaId || job.saga_id,
      correlationId: correlationId || job.correlation_id,
      transaction
    });

    const locked = await SettlementJob.findByPk(job.id, {
      transaction,
      lock: transaction.LOCK.UPDATE
    });
    if (!locked || locked.status === 'settled') return;
    locked.status = 'pending';
    locked.eligible_at = new Date();
    locked.metadata = {
      ...(locked.metadata || {}),
      codRemittance: {
        carrier,
        referenceId: referenceId || null,
        remittedAmount: remittanceAmount,
        receivedAt: new Date().toISOString()
      }
    };
    await locked.save({ transaction });
  });

  const refreshed = await SettlementJob.findByPk(job.id);
  return {
    ok: true,
    remitted: true,
    settlementQueued: true,
    job: refreshed.toJSON()
  };
}

async function listSettlementJobs(shopId, limit = 50) {
  const where = shopId ? { shop_id: String(shopId) } : {};
  const rows = await SettlementJob.findAll({
    where,
    order: [['created_at', 'DESC']],
    limit: Math.max(1, Math.min(Number(limit) || 50, 200))
  });
  return rows.map((row) => row.toJSON());
}

function initSettlementWorker() {
  const intervalMs = Number(process.env.SETTLEMENT_WORKER_INTERVAL_MS || 60 * 1000);
  const timer = setInterval(() => {
    processDueSettlements().catch((err) => {
      console.error('[wallet-service] settlement worker failed', err.message);
    });
  }, intervalMs);
  timer.unref?.();
}

module.exports = {
  createSettlementJobsForDeliveredOrder,
  processDueSettlements,
  recordCodRemittance,
  listSettlementJobs,
  initSettlementWorker
};
