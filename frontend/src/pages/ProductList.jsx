import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import ProductGrid from '../components/ProductGrid.jsx';
import { useCart } from '../context/CartContext.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { useToast } from '../context/ToastContext.jsx';
import useShopMap from '../hooks/useShopMap';
import useInventoryMap, { getAvailableStock } from '../hooks/useInventoryMap';

export default function ProductList() {
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const { addItem } = useCart();
  const { user } = useAuth();
  const { showToast } = useToast();
  const shopMap = useShopMap();
  const navigate = useNavigate();
  const inventoryMap = useInventoryMap(products);

  useEffect(() => {
    api.get('/products').then((res) => setProducts(res.data)).catch(() => setProducts([]));
  }, []);

  useEffect(() => {
    api.get('/categories').then((res) => setCategories(res.data)).catch(() => setCategories([]));
  }, []);

  async function addToCart(product) {
    if (!product) return;
    if (!user?.id || user.role !== 'buyer') {
      showToast('Vui lòng đăng nhập để thêm sản phẩm vào giỏ hàng', 'error');
      navigate('/login');
      return;
    }
    if (Array.isArray(product.variants) && product.variants.length > 0) {
      showToast('Vui lòng chọn biến thể trước khi thêm vào giỏ');
      navigate(`/product/${product._id || product.id}`);
      return;
    }
    if (Number(product.availableStock ?? product.quantity ?? 0) <= 0) {
      showToast('Hết hàng', 'error');
      return;
    }
    await addItem(product._id || product.id, 1);
    showToast('Đã thêm vào giỏ hàng');
  }

  const categoryMap = useMemo(() => {
    const map = new Map();
    categories.forEach((category) => map.set(category._id || category.id, category));
    return map;
  }, [categories]);

  const decoratedProducts = useMemo(
    () =>
      products.map((product) => ({
        ...product,
        availableStock: getAvailableStock(product, null, inventoryMap),
        categoryName: categoryMap.get(product.categoryId)?.name || product.categoryName,
        shopName: shopMap.get(product.shopId)?.name || product.shopName
      })),
    [products, categoryMap, shopMap, inventoryMap]
  );

  return (
    <div className="container page-section">
      <div className="section-header">
        <h2>Sàn thương mại</h2>
        <span className="section-link">Bộ lọc</span>
      </div>
      <ProductGrid products={decoratedProducts} onAdd={addToCart} detailBasePath="/product" />
    </div>
  );
}
