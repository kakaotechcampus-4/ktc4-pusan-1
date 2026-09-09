import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // 기본값은 IPv6([::1])에만 바인딩돼 127.0.0.1 로 접근하는 클라이언트가 붙지 못한다.
    // 다른 기기에서 접속해야 할 때는 `npm run dev -- --host` 로 LAN 에 노출한다.
    host: '127.0.0.1',
    port: 5173,
  },
});
