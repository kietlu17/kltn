import axios from 'axios';

const configuredBaseUrl = (import.meta.env.VITE_API_BASE_URL || '').trim();

const api = axios.create({
  // Frontend should only call api-gateway by default.
  baseURL: configuredBaseUrl || 'http://localhost:3000'
});

export const API_BASE_URL = api.defaults.baseURL;

export function resolveImageUrl(value) {
  if (!value) return '';
  if (value.startsWith('http://') || value.startsWith('https://')) return value;
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


