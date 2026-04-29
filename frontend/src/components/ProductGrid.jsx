import ProductCard from './ProductCard.jsx';

export default function ProductGrid({ products, onAdd, detailBasePath }) {
  if (!products?.length) {
    return (
      <div className="empty-state">
        <h3>Không tìm thấy sản phẩm</h3>
        <p>Hãy tải lại trang hoặc thêm sản phẩm mới từ trang người bán.</p>
      </div>
    );
  }

  return (
    <div className="product-grid">
      {products.map((product) => (
        <ProductCard
          key={product._id || product.id}
          product={product}
          onAdd={onAdd}
          detailBasePath={detailBasePath}
        />
      ))}
    </div>
  );
}
