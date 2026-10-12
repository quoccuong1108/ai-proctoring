# EduShield AI — Sinh viên thi trên điện thoại (Android + iOS)

Sinh viên mở **cùng một trang web** trên điện thoại (Chrome/Safari) và có thể "cài" thành biểu tượng trên màn hình chính (PWA). Giảng viên vẫn dùng web trên máy tính để tải đề, xem log và vi phạm như cũ. Không cần build APK/IPA, không cần máy Mac.

## 1. Chạy hệ thống trên laptop Windows

Camera trên điện thoại **chỉ hoạt động qua HTTPS**, nên cần một địa chỉ HTTPS trỏ về laptop. Cách dễ nhất là dùng Cloudflare Tunnel.

**Bước 1 — Build giao diện (làm lại mỗi khi sửa code frontend):**

```powershell
cd frontend
npm ci
npm run build
```

**Bước 2 — Chạy backend** (backend giờ phục vụ luôn giao diện đã build, cùng địa chỉ với API):

```powershell
cd backend
.venv\Scripts\activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

Không cần cài thêm thư viện Python nào mới. Tạo tài khoản giảng viên từ thư mục gốc bằng `python backend/create_teacher.py GV-2026 "Họ tên giảng viên"`; mật khẩu được nhập ẩn bằng `getpass`. Giảng viên đăng nhập bằng tài khoản riêng, không dùng chung mật khẩu trong giao diện.

**Bước 3 — Mở tunnel HTTPS** (cài một lần: `winget install --id Cloudflare.cloudflared`):

```powershell
cloudflared tunnel --url http://localhost:8000
```

Terminal in ra địa chỉ dạng `https://xxxx-xxxx.trycloudflare.com`. Gửi địa chỉ này cho sinh viên. Địa chỉ đổi mỗi lần chạy lại tunnel; laptop phải bật và giữ nguyên hai cửa sổ terminal (backend + tunnel) suốt buổi thi. Có thể dùng `ngrok http 8000` thay thế.

Giảng viên dùng chính địa chỉ đó (hoặc `http://localhost:8000` trên laptop) để đăng nhập bằng mã giảng viên và mật khẩu tài khoản.

> Đang phát triển thì vẫn dùng `npm run dev` như trước. Vite giờ mở cho cả mạng LAN và tên miền tunnel (`host: true`, `allowedHosts: true`).

## 2. Sinh viên cài như ứng dụng (tùy chọn)

- **Android (Chrome):** menu ⋮ → *Cài đặt ứng dụng* (hoặc *Thêm vào màn hình chính*).
- **iPhone/iPad (Safari):** nút Chia sẻ → *Thêm vào Màn hình chính*.

Không cài cũng được, cứ mở địa chỉ trong trình duyệt. Khi vào thi trình duyệt sẽ xin quyền camera — chọn *Cho phép*.

## 3. Đã thay đổi gì so với bản PC

| Nội dung | Thay đổi |
|---|---|
| Địa chỉ API | Gom vào `frontend/src/config.js`, có thể đổi bằng biến `VITE_API_BASE_URL` (dùng nếu sau này đóng gói APK). |
| Phục vụ web | `backend/main.py` phục vụ `frontend/dist` (có SPA fallback, chặn path traversal). Chưa build thì bỏ qua, chạy như cũ. |
| Vi phạm chuyển tab / mất focus / thoát fullscreen | **Trước đây chỉ hiện ở màn hình sinh viên, không gửi lên server.** Nay gửi lên `/api/violations` để giảng viên thấy trong log (có ảnh chụp). Áp dụng cả PC lẫn điện thoại. |
| Một lần chuyển app đếm 1 lần | Chống đếm trùng khi `visibilitychange` và `blur` cùng bắn. |
| Đăng ký vào thi | Sinh viên chọn môn và đề trong danh sách, gửi yêu cầu và chờ giảng viên duyệt. Các thao tác thi cần phiên `X-Exam-Session` được cấp theo yêu cầu đã duyệt. |
| Đồng hồ làm bài | Server ghi giờ bắt đầu (`POST /api/exams/code/{mã}/start`, bảng mới `exam_starts` tự tạo). Tải lại trang hoặc đổi thiết bị sẽ **tiếp tục với thời gian còn lại**, không được cấp lại từ đầu. Đồng hồ tính theo mốc kết thúc nên không chậm khi app xuống nền. Không thể bắt đầu bài thi nếu API xác thực phiên gặp lỗi. Cột `started_at` của bài nộp giờ được điền. |
| Camera/AI | Video phân tích không còn `display:none` (iOS không phát video này); thêm `play()` tường minh và giới hạn chờ 8 giây; MediaPipe tự lùi về CPU nếu GPU không khởi tạo được; điện thoại quét 500 ms/lần (ngưỡng quay mặt vẫn ≈ 3,6 giây); ảnh vi phạm giữ đúng tỷ lệ khung hình. |
| Giao diện | `viewport-fit=cover`, `dvh`, vùng an toàn tai thỏ, ô nhập ≥16px trên màn hình cảm ứng (tránh iOS tự phóng to), hộp cảnh báo vừa màn hình nhỏ, manifest + icon PWA. |

Không đổi: đăng nhập, cách chấm điểm, cấu trúc các bảng cũ, các endpoint cũ, thuật toán nhận diện và ngưỡng vi phạm.

## 4. Giới hạn cần biết (trình duyệt không khóa được điện thoại)

- **iPhone không có toàn màn hình** cho trang web, nên không ép được fullscreen; hệ thống chỉ phát hiện và ghi log việc rời app/khóa màn hình. Trên Android Chrome vẫn có fullscreen. Nếu trường yêu cầu, có thể hướng dẫn sinh viên bật *Truy cập được hướng dẫn* (Guided Access) trên iPhone hoặc *Ghim màn hình* trên Android — do sinh viên tự bật, hệ thống không kiểm tra được.
- **Camera tạm dừng khi app xuống nền** (cả Android lẫn iOS). Trong lúc đó không có giám sát hình ảnh; chỉ còn log chuyển app.
- Điện thoại cần Internet: mô hình AI và thư viện MediaPipe tải từ `cdn.jsdelivr.net` và `storage.googleapis.com` mỗi phiên thi (lần đầu vài MB).
- Điện thoại vừa làm bài vừa chạy AI sẽ nóng và hao pin; nên cắm sạc.
- Cần lưu ý các mục "PHONE_DETECTED": trên điện thoại, camera trước nhìn sinh viên, nên chỉ phát hiện được thiết bị *khác* lọt vào khung hình.

## 5. Danh sách kiểm tra trên thiết bị thật (nên làm trước buổi thi)

1. Điện thoại Android + iPhone: mở địa chỉ tunnel, đăng nhập SV, chọn môn và đề, chờ giảng viên duyệt, *Bắt đầu làm bài* → cấp quyền camera → trạng thái AI chuyển sang "Sẵn sàng".
2. Khung camera hiện hình và huy hiệu AI đổi khi che camera / quay mặt > 4 giây.
3. Chuyển sang app khác rồi quay lại → hiện cảnh báo; trên máy giảng viên xuất hiện log `TAB_SWITCH` / `WINDOW_BLUR`.
4. Tải lại trang giữa chừng, vào lại cùng mã đề → đồng hồ tiếp tục, không quay về đầy đủ giờ.
5. Nộp bài → giảng viên thấy điểm và số lần vi phạm trong bảng điểm.

Các mục 1–2 phụ thuộc thiết bị (đặc biệt MediaPipe trên iOS Safari) và **chưa được kiểm thử trên máy thật** trong lần phát triển này.

## 6. Nếu sau này cần file APK (Android)

Frontend đã sẵn sàng để bọc bằng Capacitor và build trên Windows bằng Android Studio: đặt `VITE_API_BASE_URL=https://<địa-chỉ-server>/api` trong `frontend/.env.production`, rồi `npm run build`. iOS native cần máy Mac và tài khoản Apple Developer, nên với iPhone dùng PWA như trên.
