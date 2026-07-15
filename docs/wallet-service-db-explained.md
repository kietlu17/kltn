# Wallet Service Database

This document explains the wallet database after the double-entry update. The DBML version is in `docs/wallet-service-db.dbml`.

## Design Goal

The wallet service now has two layers:

| Layer | Tables | Purpose |
| --- | --- | --- |
| Legacy buyer wallet | `wallets`, `wallet_balances`, `wallet_ledger_entries` | Keep current buyer wallet API and transaction history working. This is single-sided ledger data. |
| Financial double-entry ledger | `accounts`, `account_balances`, `ledger_transactions`, `ledger_entries`, `payout_requests` | Source of truth for money movement between buyer, platform, shop, payout, and external bank accounts. |

The key double-entry invariant is:

```text
For every completed ledger_transaction:
  entry_count >= 2
  debit_amount = credit_amount
  debit_amount = amount
```

## Tables

### `wallets`

Legacy buyer wallet identity table. It is keyed by `user_id + currency`.

Used by:

- `GET /payments/wallet/:userId`
- buyer topup
- buyer wallet payment
- buyer refund history

### `wallet_balances`

Legacy balance snapshot for the buyer wallet.

Important fields:

- `available_balance`: spendable buyer wallet balance.
- `locked_balance`: reserved for future hold logic.
- `version`: optimistic/version marker for updates.

Current role: compatibility state for existing UI/API. New financial correctness is handled by `account_balances`.

### `wallet_ledger_entries`

Legacy one-sided transaction history. It records changes from a single wallet point of view.

Example:

```text
buyer wallet debit 100000 for order payment
```

It does not fully answer:

```text
Where did the money go?
Which receiving account got the credit?
Was total debit equal to total credit?
```

That is why `ledger_transactions` and `ledger_entries` were added.

### `accounts`

General financial account identity table.

Common account types:

| owner_type | account_type | Meaning |
| --- | --- | --- |
| `buyer` | `buyer_wallet` | Buyer wallet account. |
| `platform` | `platform_clearing` | Platform holding/clearing account after buyer payment. |
| `shop` | `seller_balance` | Shop available balance. |
| `shop` | `payout_pending` | Shop payout amount being processed. |
| `external` | `external_bank` | External bank/payment rail account. Usually allowed negative as a system counterparty. |

Unique key:

```text
owner_type + owner_id + account_type + currency
```

### `account_balances`

Current balance snapshot for each account.

During a transfer, wallet service locks relevant rows with `FOR UPDATE`, then updates balances and ledger entries inside the same DB transaction.

Important fields:

- `available_balance`
- `locked_balance`
- `version`

### `ledger_transactions`

Parent record for a double-entry transaction.

Important fields:

- `reference_id`: unique business reference.
- `idempotency_key`: optional duplicate protection key.
- `type`: transaction type.
- `status`: `pending`, `completed`, or failed-like status.
- `amount`: expected balanced transaction amount.
- `debit_amount`: stored debit total after entries are written.
- `credit_amount`: stored credit total after entries are written.
- `entry_count`: stored number of ledger entries.

Completed transactions must satisfy:

```text
debit_amount = credit_amount = amount
entry_count >= 2
```

### `ledger_entries`

Child lines of a `ledger_transaction`.

Each row is one side of the accounting movement:

```text
debit account A
credit account B
```

Important fields:

- `transaction_id`
- `account_id`
- `direction`: `debit` or `credit`
- `amount`
- `available_before`
- `available_after`

### `payout_requests`

Represents a shop withdrawal request.

The money flow is:

```text
seller_balance -> payout_pending -> external_bank
```

Important statuses:

- `requested`
- `processing`
- `completed`
- `failed`

### `inbox_events`

Kafka idempotency table for consumed messages.

Prevents the same Kafka message from being processed twice.

### `outbox_events`

Transactional outbox table for produced messages.

Events are written in the same DB transaction as the money update, then published asynchronously.

## Money Transactions

### 1. Buyer Topup

Used by `topupWallet` / `creditWallet`.

Double-entry movement:

```text
Debit  external_bank
Credit buyer_wallet
```

Legacy mirror:

```text
wallet_balances.available_balance += amount
wallet_ledger_entries: direction = credit
```

### 2. Buyer Pays Order With Wallet

Used by `debitForOrder`.

Double-entry movement:

```text
Debit  buyer_wallet
Credit platform_clearing
```

Legacy mirror:

```text
wallet_balances.available_balance -= amount
wallet_ledger_entries: direction = debit
```

### 3. Buyer Pays Order With Bank Transfer

Used by `recordExternalPaymentForOrder`.

Double-entry movement:

```text
Debit  external_bank
Credit platform_clearing
```

Legacy mirror:

```text
wallet_ledger_entries: direction = none
```

The buyer wallet balance does not change, but the platform clearing account receives the money.

### 4. Order Paid Settlement To Shop

Triggered by `order.paid`, handled by wallet-service.

Double-entry movement:

```text
Debit  platform_clearing
Credit seller_balance
```

In the current MVP, settlement happens at `order.paid`. For production marketplace behavior, this should later move to a settlement-eligible event such as delivered plus return/dispute window ended.

### 5. Refund Buyer

Used by `refundOrderToWallet`.

If the order was already settled to shop, first reverse settlement:

```text
Debit  seller_balance
Credit platform_clearing
```

Then refund buyer:

```text
Debit  platform_clearing
Credit buyer_wallet
```

Legacy mirror:

```text
wallet_balances.available_balance += amount
wallet_ledger_entries: direction = credit
```

### 6. Shop Requests Payout

Used by `requestPayout`.

Double-entry movement:

```text
Debit  seller_balance
Credit payout_pending
```

Creates a `payout_requests` row with status `processing`.

### 7. Payout Completed

Used by `completePayout`.

Double-entry movement:

```text
Debit  payout_pending
Credit external_bank
```

Marks `payout_requests.status = completed`.

### 8. Payout Failed

Used by `failPayout`.

Double-entry movement:

```text
Debit  payout_pending
Credit seller_balance
```

Marks `payout_requests.status = failed`.

## ACID Logic

Every money movement runs in one DB transaction:

```text
BEGIN
  find or create ledger_transaction by reference_id/idempotency_key
  lock account_balances rows in account_id order
  validate balance and currency
  insert debit/credit ledger_entries
  update account_balances
  recompute debit/credit totals from DB
  update ledger_transactions debit_amount, credit_amount, entry_count
  mark ledger_transaction completed
  insert outbox event if needed
COMMIT
```

If any step fails, the DB transaction rolls back.

## Double-Entry Guards

Current protection layers:

| Layer | Protection |
| --- | --- |
| Service validation | Requires at least 2 entries, valid `debit/credit` directions, positive amount, debit total equals credit total. |
| Runtime verification | After entries are inserted, totals are recomputed from DB before marking transaction completed. |
| DB columns | `ledger_transactions` stores `debit_amount`, `credit_amount`, and `entry_count`. |
| DB check constraints | Completed transaction must be balanced. Entry direction must be valid and amount positive. |
| Reconciliation CLI | `npm.cmd run ledger:reconcile` reports imbalanced completed transactions. |

## Benchmark Summary

These are observed local benchmark results from the current development environment.

| Stage | Accounts | Concurrency | Duration | Completed | TPS | p50 ms | p95 ms | p99 ms | Failed | Balance OK | Double-Entry OK |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Before strict double-entry verification | 100 | 50 | 30s | 6,375 | 211.10 | 234.26 | 270.62 | 286.76 | 0 | yes | not measured in benchmark |
| After strict double-entry, smoke test | 10 | 5 | 2s | 259 | 127.59 | 36.56 | 62.90 | 83.12 | 0 | yes | yes |
| After strict double-entry, larger run | 1,000 | 100 | 30s | 5,204 | 170.54 | 589.83 | 635.27 | 662.33 | 0 | yes | yes |

The larger run produced this double-entry result:

| Metric | Value |
| --- | ---: |
| `transactionCount` | 6,773 |
| `entryCount` | 13,546 |
| `transactionAmount` | 1,000,286,090 |
| `debitAmount` | 1,000,286,090 |
| `creditAmount` | 1,000,286,090 |
| `issueCount` | 0 |

Interpretation:

```text
entryCount = transactionCount * 2
debitAmount = creditAmount = transactionAmount
issueCount = 0
```

So the ledger is balanced for the benchmark run.

## Useful Commands

Run TPS benchmark:

```powershell
cd wallet-service
npm.cmd run ledger:tps
```

Run benchmark with custom parameters:

```powershell
$env:TPS_ACCOUNT_COUNT='1000'
$env:TPS_CONCURRENCY='100'
$env:TPS_DURATION_SECONDS='30'
$env:TPS_WARMUP_SECONDS='3'
npm.cmd run ledger:tps
```

Run hot-account contention test:

```powershell
$env:TPS_HOT_ACCOUNT='true'
npm.cmd run ledger:tps
```

Run reconciliation:

```powershell
npm.cmd run ledger:reconcile
```
