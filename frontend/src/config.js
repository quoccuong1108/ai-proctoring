/**
 * Cấu hình dùng chung cho toàn bộ frontend.
 *
 * API_BASE_URL:
 *   - Mặc định "/api": chạy qua proxy của Vite (npm run dev) hoặc khi FastAPI phục vụ
 *     luôn thư mục frontend/dist (cùng một địa chỉ cho web và API) — đây là cách dùng
 *     cho web PC và web trên điện thoại.
 *   - Nếu sau này đóng gói thành app (Capacitor/APK) thì web nằm ở địa chỉ nội bộ của app,
 *     cần đặt VITE_API_BASE_URL=https://ten-mien-cua-ban/api trong file frontend/.env.production
 *     trước khi chạy `npm run build`.
 */
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "/api").replace(
  /\/+$/,
  "",
);

/**
 * Nhận diện thiết bị di động (điện thoại/máy tính bảng) để giảm tải AI và bỏ qua
 * các tính năng trình duyệt di động không hỗ trợ. iPadOS 13+ báo là "Macintosh" nên
 * phải kiểm tra thêm số điểm chạm.
 */
export const IS_MOBILE_DEVICE =
  typeof navigator !== "undefined" &&
  (/Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent) ||
    (navigator.maxTouchPoints > 1 && /Mac/i.test(navigator.platform || "")));
