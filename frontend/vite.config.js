import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

const proxiedRoutes = [
  '/auth',
  '/users',
  '/shops',
  '/products',
  '/inventory',
  '/vouchers',
  '/uploads',
  '/categories',
  '/cart',
  '/orders',
  '/payments',
  '/reviews',
  '/chat'
];

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const gatewayTarget = env.VITE_API_GATEWAY_URL || 'http://localhost:3000';
  const proxy = Object.fromEntries(
    proxiedRoutes.map((route) => [
      route,
      {
        target: gatewayTarget,
        changeOrigin: true,
        secure: false
      }
    ])
  );

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy
    }
  };
});
