import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import api from '../services/api';
import { useAuth } from './AuthContext.jsx';

const CartContext = createContext(null);

export function CartProvider({ children }) {
  const { user, role, authReady } = useAuth();
  const [cartProducts, setCartProducts] = useState([]);
  const userId = user?.id || user?.userId || user?._id;
  const canUseCart = authReady && role === 'buyer';

  const loadCart = useCallback(async () => {
    if (!authReady) return;
    if (!canUseCart) {
      setCartProducts([]);
      return;
    }
    try {
      const res = await api.get('/cart/user');
      setCartProducts(res.data?.products || []);
    } catch {
      setCartProducts([]);
    }
  }, [authReady, userId, canUseCart]);

  useEffect(() => {
    loadCart();
  }, [loadCart]);

  const addItem = async (productId, quantity = 1, variantId = null) => {
    if (!userId || !canUseCart) return;
    await api.post('/cart/add', { userId, productId, variantId, quantity });
    await loadCart();
  };

  const removeItem = async (productId, variantId = null) => {
    if (!userId || !canUseCart) return;
    await api.post('/cart/remove', { userId, productId, variantId });
    await loadCart();
  };

  const updateItem = async (productId, quantity, variantId = null) => {
    if (!userId || !canUseCart) return;
    await api.post('/cart/update', { userId, productId, variantId, quantity: Number(quantity) });
    await loadCart();
  };

  const clearCart = () => {
    setCartProducts([]);
  };

  const cartCount = cartProducts.reduce((sum, item) => sum + Number(item.quantity || 0), 0);

  const value = useMemo(
    () => ({
      cartProducts,
      cartCount,
      refreshCart: loadCart,
      addItem,
      removeItem,
      updateItem,
      clearCart
    }),
    [cartProducts, cartCount, loadCart]
  );

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

export function useCart() {
  const ctx = useContext(CartContext);
  if (!ctx) throw new Error('useCart must be used within CartProvider');
  return ctx;
}


