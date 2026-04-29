import { useEffect, useMemo, useState } from 'react';
import api from '../services/api';

let cachedShops = null;
let inflight = null;

async function fetchShops() {
  if (cachedShops) return cachedShops;
  if (inflight) return inflight;
  inflight = api
    .get('/shops')
    .then((res) => {
      cachedShops = Array.isArray(res.data) ? res.data : [];
      return cachedShops;
    })
    .catch(() => {
      cachedShops = [];
      return cachedShops;
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

export default function useShopMap() {
  const [shops, setShops] = useState(cachedShops || []);

  useEffect(() => {
    let mounted = true;
    fetchShops().then((data) => {
      if (mounted) setShops(Array.isArray(data) ? data : []);
    });
    return () => {
      mounted = false;
    };
  }, []);

  return useMemo(() => {
    const map = new Map();
    (shops || []).forEach((shop) => {
      map.set(shop?._id || shop?.id, shop);
    });
    return map;
  }, [shops]);
}


