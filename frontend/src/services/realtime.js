import { io } from 'socket.io-client';
import { API_BASE_URL } from './api';

const configuredRealtimeBaseUrl = (import.meta.env.VITE_REALTIME_BASE_URL || '').trim();
const configuredGatewayUrl = (import.meta.env.VITE_API_GATEWAY_URL || '').trim();

export const REALTIME_BASE_URL = configuredRealtimeBaseUrl || API_BASE_URL || configuredGatewayUrl || '';

export function getStoredAuthToken() {
  return sessionStorage.getItem('token') || localStorage.getItem('token') || '';
}

export function createLiveSocket(liveId) {
  const baseUrl = REALTIME_BASE_URL || undefined;
  return io(baseUrl, {
    path: '/realtime/socket.io',
    transports: ['websocket', 'polling'],
    auth: {
      token: getStoredAuthToken(),
      liveId
    }
  });
}
