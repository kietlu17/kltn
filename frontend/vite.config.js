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
  '/chat',
  '/lives'
];

function shouldServeSpa(req) {
  return req.method === 'GET' && String(req.headers.accept || '').includes('text/html');
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const gatewayTarget = env.VITE_API_GATEWAY_URL || 'http://localhost:3000';
  const livekitTarget = env.VITE_LIVEKIT_URL || 'http://localhost:7880';
  const proxy = Object.fromEntries(
    proxiedRoutes.map((route) => [
      route,
      {
        target: gatewayTarget,
        changeOrigin: true,
        secure: false,
        bypass: (req) => (shouldServeSpa(req) ? req.url : undefined)
      }
    ])
  );

  proxy['/livekit'] = {
    target: livekitTarget,
    changeOrigin: true,
    secure: false,
    ws: true,
    rewrite: (path) => path.replace(/^\/livekit/, '')
  };

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy
    }
  };
});
