export const ORDER_STATUS_LABELS = {
  all: 'Tất cả',
  pending_payment: 'Chờ thanh toán',
  payment_processing: 'Đang xử lý thanh toán',
  paid: 'Đã thanh toán',
  confirmed: 'Đã xác nhận',
  shipped: 'Đang giao',
  delivered: 'Đã giao',
  payment_failed: 'Thanh toán thất bại',
  cancelled: 'Đã hủy',
  completed: 'Hoàn tất'
};

export const PAYMENT_METHOD_LABELS = {
  cod: 'Thanh toán khi nhận hàng',
  wallet: 'Ví',
  bank_transfer: 'Chuyển khoản ngân hàng',
  sepay: 'SePay QR'
};

export const VOUCHER_STATUS_LABELS = {
  active: 'Đang bật',
  inactive: 'Đã tắt',
  expired: 'Hết hạn'
};

export const DISPUTE_STATUS_LABELS = {
  open: 'Đang chờ xử lý',
  resolved: 'Đã giải quyết',
  rejected: 'Đã từ chối'
};

export function formatOrderStatus(status) {
  const key = String(status || '').toLowerCase();
  return ORDER_STATUS_LABELS[key] || 'Không rõ';
}

export function formatPaymentMethod(method) {
  const key = String(method || '').toLowerCase();
  return PAYMENT_METHOD_LABELS[key] || 'Không có';
}

export function formatVoucherStatus(status) {
  const key = String(status || '').toLowerCase();
  return VOUCHER_STATUS_LABELS[key] || 'Không rõ';
}

export function formatDisputeStatus(status) {
  const key = String(status || '').toLowerCase();
  return DISPUTE_STATUS_LABELS[key] || 'Không rõ';
}
