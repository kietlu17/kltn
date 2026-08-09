import { resolveImageUrl } from '../services/api';

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
}

export default function CartItem({ item, onRemove, onUpdate, selected, onSelect }) {
  const subtotal = Number(item?.price || 0) * Number(item?.quantity || 0);
  const image = resolveImageUrl(item?.image || item?.imageUrl || item?.product?.imageUrl || '');
  const lineId = item?.lineId || `${item?.productId || item?.id}::${item?.variantId || ''}`;
  const availableQty = Number(item?.availableQty ?? 0);
  const quantity = Number(item?.quantity || 1);
  const hasEnoughStock = availableQty >= quantity;

  return (
    <div className="cart-row">
      <div className="cart-cell cart-product">
        <input className="cart-check" type="checkbox" checked={Boolean(selected)} onChange={() => onSelect?.(lineId)} />
        <div className="cart-thumb">
          {image ? <img src={image} alt={item?.name || 'Sản phẩm'} /> : <div className="image-placeholder" />}
        </div>
        <div>
          <div className="cart-name">{item?.name || item?.productName || 'Sản phẩm chưa đặt tên'}</div>
          <div className="cart-shop">{item?.shopName || 'Shop'}</div>
          {item?.variantName && <div className="muted">Biến thể: {item.variantName}</div>}
          {!hasEnoughStock && <div className="stock-inline">Không đủ tồn kho</div>}
        </div>
      </div>
      <div className="cart-cell">{formatPrice(item?.price)}</div>
      <div className="cart-cell">
        <input
          className="qty-input"
          type="number"
          min="1"
          max={availableQty || undefined}
          value={item?.quantity || 1}
          onChange={(event) => onUpdate?.(item?.productId || item?.id, event.target.value, item?.variantId || null)}
          disabled={availableQty <= 0}
        />
      </div>
      <div className="cart-cell">{formatPrice(subtotal)}</div>
      <div className="cart-cell">
        <button className="btn btn-ghost" onClick={() => onRemove?.(item?.productId || item?.id, item?.variantId || null)}>
          Xóa
        </button>
      </div>
    </div>
  );
}
