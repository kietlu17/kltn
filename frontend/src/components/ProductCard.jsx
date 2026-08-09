import { Link } from 'react-router-dom';
import { resolveImageUrl } from '../services/api';

function formatPrice(value) {
  const number = Number(value || 0);
  return number.toLocaleString('vi-VN', { style: 'currency', currency: 'VND' });
}

export default function ProductCard({ product, onAdd, detailBasePath = '/product' }) {
  const id = product?._id || product?.id;
  const image = resolveImageUrl(product?.images?.[0] || product?.imageUrl || product?.image || '');
  const shop = product?.shopName || product?.shop?.name || 'Cửa hàng chính thức';
  const shopId = product?.shopId || product?.shop?._id || product?.shop?.id;
  const category = product?.categoryName || product?.category || '';
  const availableStock = Number(product?.availableStock ?? product?.quantity ?? 0);
  const isOutOfStock = availableStock <= 0;
  const sold = Number(product?.sold ?? 0);
  const variantPrices = Array.isArray(product?.variants)
    ? product.variants
      .map((variant) => Number(variant?.price))
      .filter((price) => Number.isFinite(price) && price >= 0)
    : [];

  const hasVariants = variantPrices.length > 0;
  const minVariantPrice = hasVariants ? Math.min(...variantPrices) : null;
  const maxVariantPrice = hasVariants ? Math.max(...variantPrices) : null;
  const priceLabel = hasVariants
    ? (minVariantPrice === maxVariantPrice
      ? formatPrice(minVariantPrice)
      : `${formatPrice(minVariantPrice)} - ${formatPrice(maxVariantPrice)}`)
    : formatPrice(product?.price);

  return (
    <div className="product-card">
      <Link to={`${detailBasePath}/${id}`} className="product-image">
        {image ? <img src={image} alt={product?.name || 'Sản phẩm'} /> : <div className="image-placeholder" />}
      </Link>

      <div className="product-body">
        <Link to={`${detailBasePath}/${id}`} className="product-name">
          {product?.name || 'Sản phẩm chưa đặt tên'}
        </Link>
        {category && <span className="product-category">{category}</span>}
        {isOutOfStock && <span className="stock-badge">Hết hàng</span>}

        <div className="product-meta">
          <span className="product-price">{priceLabel}</span>
          <span className="product-sold">Đã bán: {sold}</span>
          {shopId ? (
            <Link to={`/shop/${shopId}`} className="product-shop shop-link">
              {shop}
            </Link>
          ) : (
            <span className="product-shop">{shop}</span>
          )}
        </div>

        <button
          className="btn btn-primary btn-full"
          onClick={() => onAdd?.(product)}
          disabled={isOutOfStock}
        >
          Thêm vào giỏ
        </button>
      </div>
    </div>
  );
}
