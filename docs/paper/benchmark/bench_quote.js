// Protocol-level benchmark of order-service checkoutController (quote -> confirm).
// The real controller is loaded; its model, commerce-data service and HTTP
// client are replaced by in-memory doubles. The double's conditional update is
// atomic (single-threaded JS), mirroring a SQL UPDATE ... WHERE status IN (...).
// Usage: node bench_quote.js <order-service dir> <out.json>
const path = require('path');
const fs = require('fs');
const Module = require('module');
const crypto = require('crypto');

const [, , ORDER_DIR, OUT] = process.argv;
const controllerPath = path.resolve(ORDER_DIR, 'src/controllers/checkoutController.js');

// ---- doubles -------------------------------------------------------------
const db = new Map();
let price = 250000;
let orderFail = 0; // number of next order calls that fail with 503
const orders = new Map(); // idempotency key -> order
let orderCalls = 0;
// Ablation switches (E6). Defaults reproduce the deployed protocol.
const flags = { atomicClaim: true, idempotentOrders: true, reprice: true };
let lostResponses = 0; // next order calls that create the order but lose the reply (504)

function row(data) {
  const r = { ...data };
  r.toJSON = () => ({ ...r });
  r.save = async () => { db.set(r.id, { ...stripFns(r) }); return r; };
  return r;
}
function stripFns(r) { const o = {}; for (const k of Object.keys(r)) if (typeof r[k] !== 'function') o[k] = r[k]; return o; }

const CheckoutQuote = {
  async create(data) { const id = crypto.randomUUID(); const r = row({ id, ...data }); db.set(id, stripFns(r)); return r; },
  async findByPk(id) { const d = db.get(id); return d ? row(JSON.parse(JSON.stringify(d))) : null; },
  async update(values, { where }) {
    await new Promise((res) => setImmediate(res)); // yield, like a DB round trip
    const d = db.get(where.id);
    if (!d) return [0];
    if (flags.atomicClaim && !where.status.includes(d.status)) return [0];
    Object.assign(d, values); return [1];
  },
};
const commerceData = {
  async canonicalizeProducts(products) {
    await new Promise((res) => setImmediate(res));
    return (products || []).map((p) => ({ productId: p.productId, variantId: p.variantId || null,
      quantity: Number(p.quantity),
      // Without re-pricing, a stored quote line keeps the price it was quoted at.
      price: !flags.reprice && p.price !== undefined ? Number(p.price) : price,
      shopId: 'shop-1' }));
  },
  async ownedAddress() { return { line: 'Ha Noi' }; },
  async requestJson() { return []; },
  withAgent: (_u, o) => o,
};
async function fakeFetch(_url, opts) {
  orderCalls += 1;
  const callId = orderCalls; // captured before yielding, so concurrent calls stay distinct
  await new Promise((res) => setImmediate(res));
  const key = flags.idempotentOrders ? opts.headers['Idempotency-Key'] : `call-${callId}`;
  if (orderFail > 0) { orderFail -= 1; return { ok: false, status: 503, text: async () => JSON.stringify({ message: 'unavailable' }) }; }
  if (!orders.has(key)) {
    const body = JSON.parse(opts.body);
    const subtotal = body.products.reduce((s, i) => s + i.price * i.quantity, 0);
    orders.set(key, { id: orders.size + 1, subtotal_price: subtotal, total_price: subtotal, unit_price: body.products[0].price });
  }
  if (lostResponses > 0) { lostResponses -= 1; return { ok: false, status: 504, text: async () => '' }; }
  return { ok: true, status: 201, text: async () => JSON.stringify(orders.get(key)) };
}

const realLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === '../models/CheckoutQuote') return CheckoutQuote;
  if (request === '../services/commerceData') return commerceData;
  if (request === 'node-fetch') return fakeFetch;
  return realLoad.apply(this, arguments);
};
const { createCheckoutQuote, confirmCheckout } = require(controllerPath);

function call(handler, { body = {}, params = {}, headers = { 'x-user-id': 'u1', 'x-user-role': 'buyer' } }) {
  return new Promise((resolve) => {
    const res = { code: 200, status(c) { this.code = c; return this; }, json(p) { resolve({ status: this.code, body: p }); return this; } };
    handler({ body, params, headers }, res);
  });
}
const BASE = { userId: 'u1', sessionId: 's1', products: [{ productId: 'p1', variantId: 'v1', quantity: 1 }], addressId: 'a1', paymentMethod: 'cod' };
async function quote(extra = {}) { return call(createCheckoutQuote, { body: { ...BASE, ...extra } }); }
async function confirm(q, token, extra = {}) {
  return call(confirmCheckout, { params: { id: q.quoteId }, body: { userId: 'u1', sessionId: 's1', confirmationToken: token, ...extra } });
}
function reset() { db.clear(); orders.clear(); price = 250000; orderFail = 0; orderCalls = 0; lostResponses = 0; }

(async () => {
  const cases = [];
  async function run(name, expected, fn) {
    reset();
    const t0 = process.hrtime.bigint();
    const observed = await fn();
    const ms = Number(process.hrtime.bigint() - t0) / 1e6;
    cases.push({ case: name, expected, observed, orders: orders.size, pass: JSON.stringify(observed) === JSON.stringify(expected), ms });
  }

  await run('Q1 valid confirm creates one order', { status: 201, orders: 1 }, async () => {
    const q = (await quote()).body; const r = await confirm(q, q.confirmationToken); return { status: r.status, orders: orders.size };
  });
  await run('Q2 replayed confirm returns same order', { first: 201, second: 200, replayed: true, orders: 1 }, async () => {
    const q = (await quote()).body; const a = await confirm(q, q.confirmationToken); const b = await confirm(q, q.confirmationToken);
    return { first: a.status, second: b.status, replayed: b.body.replayed === true, orders: orders.size };
  });
  await run('Q3 wrong confirmation token', { status: 403, orders: 0 }, async () => {
    const q = (await quote()).body; const r = await confirm(q, 'x'.repeat(43)); return { status: r.status, orders: orders.size };
  });
  await run('Q4 other session', { status: 403, orders: 0 }, async () => {
    const q = (await quote()).body; const r = await confirm(q, q.confirmationToken, { sessionId: 's2' }); return { status: r.status, orders: orders.size };
  });
  await run('Q5 other buyer', { status: 404, orders: 0 }, async () => {
    const q = (await quote()).body;
    const r = await call(confirmCheckout, { params: { id: q.quoteId }, headers: { 'x-user-id': 'u2', 'x-user-role': 'buyer' },
      body: { userId: 'u2', sessionId: 's1', confirmationToken: q.confirmationToken } });
    return { status: r.status, orders: orders.size };
  });
  await run('Q6 expired quote', { status: 410, orders: 0 }, async () => {
    const q = (await quote()).body; db.get(q.quoteId).expires_at = new Date(Date.now() - 1000);
    const r = await confirm(q, q.confirmationToken); return { status: r.status, orders: orders.size };
  });
  await run('Q7 price changed between quote and confirm', { status: 409, code: 'QUOTE_CHANGED', orders: 0 }, async () => {
    const q = (await quote()).body; price = 260000; const r = await confirm(q, q.confirmationToken);
    return { status: r.status, code: r.body.code, orders: orders.size };
  });
  await run('Q8 wallet auto-payment refused', { status: 409, code: 'STEP_UP_REQUIRED' }, async () => {
    const r = await quote({ paymentMethod: 'wallet' }); return { status: r.status, code: r.body.code };
  });
  await run('Q9 order service fails then retry succeeds once', { first: 503, second: 201, orders: 1 }, async () => {
    const q = (await quote()).body; orderFail = 1;
    const a = await confirm(q, q.confirmationToken); const b = await confirm(q, q.confirmationToken);
    return { first: a.status, second: b.status, orders: orders.size };
  });
  for (const n of [2, 10, 50]) {
    await run(`Q10 ${n} concurrent confirms`, { created: 1, conflicts: n - 1, orders: 1 }, async () => {
      const q = (await quote()).body;
      const rs = await Promise.all(Array.from({ length: n }, () => confirm(q, q.confirmationToken)));
      return { created: rs.filter((r) => r.status === 201).length, conflicts: rs.filter((r) => r.status === 409).length, orders: orders.size };
    });
  }

  // throughput of the happy path (protocol overhead only)
  reset();
  const lat = [];
  for (let i = 0; i < 1000; i += 1) {
    const t0 = process.hrtime.bigint();
    const q = (await quote()).body; await confirm(q, q.confirmationToken);
    lat.push(Number(process.hrtime.bigint() - t0) / 1e6);
  }
  lat.sort((a, b) => a - b);
  const happyOrders = orders.size;

  // ---- E6: ablation of the server-side guards ----------------------------
  const variants = {
    'Full protocol': {},
    '- atomic claim': { atomicClaim: false },
    '- idempotency key': { idempotentOrders: false },
    '- claim and key': { atomicClaim: false, idempotentOrders: false },
    '- re-pricing': { reprice: false },
  };
  const ablation = {};
  for (const [name, change] of Object.entries(variants)) {
    Object.assign(flags, { atomicClaim: true, idempotentOrders: true, reprice: true }, change);
    const row = {};
    for (const n of [2, 10, 50]) {
      reset();
      const q = (await quote()).body;
      await Promise.all(Array.from({ length: n }, () => confirm(q, q.confirmationToken)));
      row[`orders_${n}_concurrent`] = orders.size;
    }
    reset();
    { const q = (await quote()).body; lostResponses = 1;
      await confirm(q, q.confirmationToken); await confirm(q, q.confirmationToken);
      row.orders_after_lost_reply_retry = orders.size; }
    reset();
    { const q = (await quote()).body; price = 260000; await confirm(q, q.confirmationToken);
      row.stale_price_orders = [...orders.values()].filter((o) => o.unit_price !== price).length; }
    ablation[name] = row;
  }
  Object.assign(flags, { atomicClaim: true, idempotentOrders: true, reprice: true });

  const result = { node: process.version, cases, happy_path_ms: { n: lat.length, median: lat[500], p95: lat[950] }, orders_created: happyOrders, ablation };
  console.log('ablation', JSON.stringify(ablation, null, 1));
  fs.writeFileSync(OUT, JSON.stringify(result, null, 2));
  for (const c of cases) console.log(c.pass ? 'PASS' : 'FAIL', c.case, JSON.stringify(c.observed));
  console.log('happy path', result.happy_path_ms, 'orders', orders.size);
})();
