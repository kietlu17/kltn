import { useState } from 'react';
import './AssistantSelection.css';

const formatPrice = (value) => `${Number(value || 0).toLocaleString('vi-VN')} ₫`;

// Checkbox picker the assistant returns as `selection`:
// - variant_select: tick several variants (size L and XL) to add in one go.
// - checkout_select: tick the cart lines to pay; the others stay in the cart.
// onSubmit(text, referenceProductId, action) matches the widgets' send().
export default function AssistantSelection({ selection, disabled, onSubmit }) {
  const options = Array.isArray(selection?.options) ? selection.options : [];
  const [checked, setChecked] = useState(
    () => new Set(options.filter((item) => item.checked && !item.disabled).map((item) => item.id))
  );
  if (!options.length) return null;

  const isVariant = selection.type === 'variant_select';
  const chosen = options.filter((item) => checked.has(item.id));
  const total = chosen.reduce((sum, item) => sum + Number(item.price || 0) * (isVariant ? Number(selection.quantity || 1) : 1), 0);

  function toggle(id) {
    setChecked((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function submit(event) {
    event.preventDefault();
    if (!chosen.length) return;
    const labels = chosen.map((item) => item.label).join(', ');
    if (isVariant) {
      onSubmit(`Thêm ${selection.productName || 'sản phẩm'} (${labels}) vào giỏ`, selection.productId, {
        variantIds: chosen.map((item) => item.id),
        quantity: Number(selection.quantity) || 1,
      });
    } else {
      onSubmit(`Thanh toán: ${labels}`, null, { checkoutLineIds: chosen.map((item) => item.id) });
    }
  }

  return (
    <form className="as-selection" onSubmit={submit}>
      <fieldset disabled={disabled}>
        <legend>{isVariant ? 'Chọn một hoặc nhiều phiên bản' : 'Chọn sản phẩm muốn thanh toán'}</legend>
        {options.map((item) => (
          <label key={item.id} className={`as-option${item.disabled ? ' as-disabled' : ''}`}>
            <input type="checkbox" checked={checked.has(item.id)} disabled={item.disabled}
              onChange={() => toggle(item.id)} />
            <span className="as-label">
              {item.label}
              {!isVariant && item.quantity > 1 && <small> × {item.quantity}</small>}
              {item.note && <small className="as-note"> · {item.note}</small>}
              {item.disabled && <small className="as-note"> · hết hàng</small>}
            </span>
            {Number(item.price) > 0 && <span className="as-price">{formatPrice(item.price)}</span>}
          </label>
        ))}
        <div className="as-footer">
          <span>{chosen.length ? `Đã chọn ${chosen.length} · ${formatPrice(total)}` : 'Chưa chọn mục nào'}</span>
          <button type="submit" disabled={!chosen.length}>
            {selection.submitLabel || (isVariant ? 'Thêm vào giỏ' : 'Thanh toán')}
          </button>
        </div>
      </fieldset>
    </form>
  );
}
