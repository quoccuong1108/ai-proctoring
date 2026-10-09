# EduShield AI — Báo cáo đa thiết bị

Cập nhật ngày 01/10/2026 từ https://github.com/GBinh02/AI-Protoring
Commit: `97a11fea3ed322e3c05eec84a3ff43acea11e51e`.

## Dùng trên Overleaf
1. New Project → Upload Project → chọn ZIP này.
2. Main document: `do-an.tex`; compiler: **XeLaTeX**.
3. Recompile (hoặc Recompile from scratch) để cập nhật mục lục/tham chiếu.

Bản cập nhật giữ bố cục DAU và 6 chương; bổ sung web Android/iOS, PWA,
kênh APK theo xác nhận tác giả, HTTPS tunnel, mốc bắt đầu server và 12 sơ đồ.
PDF trong gói là bản đã biên dịch, không phải PDF cũ.

## Sơ đồ
- `diagrams/EduShield_So_Do.drawio`: mở bằng diagrams.net, 12 trang chỉnh sửa được.
- `diagrams/*.pdf`: ảnh vector đã nhúng trong chương 3.
- Khi chỉnh sơ đồ bằng draw.io, xuất lại PDF và thay tệp tương ứng để cập nhật báo cáo.
- Sơ đồ: ngữ cảnh, ca sử dụng, thành phần, triển khai, DFD mức 1, ERD,
  hoạt động toàn hệ thống, tuần tự bắt đầu, tuần tự sự kiện, tuần tự nộp,
  trạng thái bài thi và luồng AI.

## Phạm vi cần đọc đúng
- `main` có web/PWA Android và iOS; chưa có cấu hình/dự án native để tái lập APK.
- Tác giả xác nhận APK và kênh iOS hoạt động; iOS trong báo cáo là Safari/PWA.
- Không khẳng định có IPA/App Store hoặc thi offline.
- `exam_starts` lưu thời điểm bắt đầu; chưa lưu nháp câu trả lời và chưa chặn
  nộp trễ trên API submit.
- Chuyển ứng dụng đã nối đường gửi về server, chưa có hàng đợi retry bền vững.

## Kiểm chứng
17 ca backend cũ được tái chạy; 11 ca bổ sung kiểm tra thời gian/sự kiện.
Cả 28 điều kiện kiểm tra đạt; M06 và M11 xác nhận giới hạn, không phải chức năng
bảo vệ đã đạt yêu cầu. Không đo AI hoặc chạy camera trên thiết bị thật tại đây.

```sh
python -m pip install -r /path/to/repo/backend/requirements.txt httpx
python code/verify_backend.py --backend /path/to/repo/backend --output /tmp/base.json
python code/verify_mobile.py --backend /path/to/repo/backend --output /tmp/mobile.json
```

Bằng chứng lần cập nhật: `evidence/*current*`, `evidence/*mobile*` và
`evidence/build-verification-current.txt`. Các tệp `results.json`, `run.log`,
`environment.json`, `source-manifest.json`, `build-verification.txt` là lịch sử
của bản gốc ngày 25–28/09/2026, không đại diện lần cập nhật.

## Thông tin cá nhân cần điền
Giữ nguyên các chỗ trống của bản gốc: `thong-tin.tex`, danh sách thành viên
trong `chuong/00-quy-uoc.tex`, lời cam đoan/cảm ơn. Điền tên, MSSV, lớp,
giảng viên và phân công thực tế trước khi nộp.
