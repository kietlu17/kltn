import { useEffect, useMemo, useState } from 'react';
import useShopMap from '../hooks/useShopMap';
import api, { getProductItems } from '../services/api';

export default function SearchBar({ initialValue = '', onSearch, onShopSelect, onProductSelect }) {
  const [query, setQuery] = useState(initialValue);
  const shopMap = useShopMap();
  const [productResults, setProductResults] = useState([]);

  useEffect(() => {
    setQuery(initialValue);
  }, [initialValue]);

  useEffect(() => {
    const normalized = query.trim();
    if (!normalized) {
      setProductResults([]);
      return;
    }

    let active = true;
    const timer = setTimeout(() => {
      api
        .get('/products', { params: { q: normalized, paginated: true, page: 1, limit: 8 } })
        .then((res) => {
          if (!active) return;
          setProductResults(getProductItems(res.data));
        })
        .catch(() => {
          if (!active) return;
          setProductResults([]);
        });
    }, 200);

    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [query]);

  const submit = (event) => {
    event.preventDefault();
    onSearch?.(query.trim());
  };

  const shops = useMemo(() => Array.from(shopMap.values()), [shopMap]);

  const matchingShops = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return [];
    return shops.filter((shop) => shop?.name?.toLowerCase().includes(normalized)).slice(0, 6);
  }, [query, shops]);

  const matchingProducts = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return [];
    return productResults.filter((product) => product?.name?.toLowerCase().includes(normalized)).slice(0, 8);
  }, [query, productResults]);

  const handleShopSelect = (shop) => {
    if (!shop) return;
    setQuery(shop.name || '');
    onShopSelect?.(shop);
  };

  const handleProductSelect = (product) => {
    if (!product) return;
    setQuery(product.name || '');
    onProductSelect?.(product);
  };

  const hasResults = matchingShops.length > 0 || matchingProducts.length > 0;

  return (
    <form className="search" onSubmit={submit}>
      <div className="search-field">
        <input
          type="text"
          placeholder="Tìm sản phẩm hoặc cửa hàng..."
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        {query.trim() && (
          <div className="search-results">
            {matchingShops.length > 0 && (
              <div className="search-section">
                <div className="search-section-title">Cửa hàng</div>
                {matchingShops.map((shop) => (
                  <button
                    key={shop._id || shop.id}
                    type="button"
                    className="search-result"
                    onClick={() => handleShopSelect(shop)}
                  >
                    <span>{shop.name}</span>
                    <span className="muted">Cửa hàng</span>
                  </button>
                ))}
              </div>
            )}

            {matchingProducts.length > 0 && (
              <div className="search-section">
                <div className="search-section-title">Sản phẩm</div>
                {matchingProducts.map((product) => (
                  <button
                    key={product._id || product.id}
                    type="button"
                    className="search-result"
                    onClick={() => handleProductSelect(product)}
                  >
                    <span>{product.name || 'Sản phẩm chưa đặt tên'}</span>
                    <span className="muted">Sản phẩm</span>
                  </button>
                ))}
              </div>
            )}

            {!hasResults && <div className="search-empty muted">Không tìm thấy kết quả</div>}
          </div>
        )}
      </div>
      <button className="btn btn-primary" type="submit">Tìm</button>
    </form>
  );
}
