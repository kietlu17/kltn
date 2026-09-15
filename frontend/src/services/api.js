import axios from 'axios';

const configuredBaseUrl = (import.meta.env.VITE_API_BASE_URL || '').trim();
const configuredProductImageBaseUrl = (import.meta.env.VITE_PRODUCT_IMAGE_BASE_URL || '').trim();

const api = axios.create({
  // Empty baseURL keeps browser requests same-origin, so Vite dev proxy can forward them.
  baseURL: configuredBaseUrl || ''
});

export const API_BASE_URL = api.defaults.baseURL;
export const PRODUCT_IMAGE_BASE_URL = configuredProductImageBaseUrl.replace(/\/+$/, '');

export function getProductItems(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.items)) return payload.items;
  return [];
}

export function resolveImageUrl(value) {
  if (!value) return '';
  if (value.startsWith('http://') || value.startsWith('https://')) return value;
  if (PRODUCT_IMAGE_BASE_URL && value.startsWith('/uploads/')) {
    const objectKey = value.replace(/^\/uploads\/+/, '');
    return `${PRODUCT_IMAGE_BASE_URL}/${objectKey.split('/').map(encodeURIComponent).join('/')}`;
  }
  if (!API_BASE_URL) return value;
  if (value.startsWith('/')) {
    return `${API_BASE_URL.replace(/\/+$/, '')}${value}`;
  }
  return value;
}

api.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('token') || localStorage.getItem('token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export default api;
