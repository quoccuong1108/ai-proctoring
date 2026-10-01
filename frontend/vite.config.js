import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    // host: true — cho phép điện thoại cùng mạng Wi‑Fi mở được máy dev qua địa chỉ IP LAN.
    // allowedHosts: true — cho phép truy cập qua tên miền tunnel HTTPS (Cloudflare Tunnel, ngrok...).
    // Lưu ý: camera trên điện thoại chỉ hoạt động qua HTTPS, nên khi thử trên điện thoại hãy dùng tunnel.
    host: true,
    allowedHosts: true,
    proxy: {
      // Ảnh snapshot giờ được phục vụ qua /api/snapshots/{filename} (có xác thực token),
      // nên chỉ cần proxy '/api' là đủ — không còn mount /snapshots tĩnh công khai ở backend nữa.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
