import { useEffect, useMemo, useState } from 'react';
import api from '../services/api';

export function inventoryKey(productId, variantId = null) {
  return `${productId || ''}::${variantId || ''}`;
}

export function getAvailableStock(product, variant, inventoryMap) {
  const productId = product?._id || product?.id;
  const variantId = variant?._id || variant?.id || null;
  const inventory = inventoryMap.get(inventoryKey(productId, variantId));
  if (inventory) return Number(inventory.availableStock ?? 0);
  return Number(variant ? variant.quantity : (product?.quantity ?? 0));
}

export default function useInventoryMap(products = []) {
  const productIds = useMemo(
    () => [...new Set((products || []).map((product) => product?._id || product?.id).filter(Boolean))],
    [products]
  );
  const productIdsKey = productIds.join('|');
  const [inventoryMap, setInventoryMap] = useState(new Map());

  useEffect(() => {
    if (!productIds.length) {
      setInventoryMap(new Map());
      return;
    }
    let active = true;
    Promise.all(
      productIds.map((productId) =>
        api
          .get(`/inventory/products/${productId}`)
          .then((res) => (Array.isArray(res.data) ? res.data : [res.data]))
          .catch(() => [])
      )
    ).then((groups) => {
      if (!active) return;
      const next = new Map();
      groups.flat().forEach((item) => {
        next.set(inventoryKey(item.productId, item.variantId), item);
      });
      setInventoryMap(next);
    });
    return () => {
      active = false;
    };
  }, [productIdsKey]);

  return inventoryMap;
}
