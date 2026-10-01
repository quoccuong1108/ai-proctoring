"""
Hệ thống Giám sát Thi Trực tuyến Thông minh EduShield AI — Backend Engine v3.0

Kiến trúc Hệ thống:
- Phát hiện AI phía Client (MediaPipe WebAssembly trên trình duyệt thí sinh)
- Cơ chế gửi bản tin hướng sự kiện (Event-driven Logging qua HTTPS RESTful API)
- Lưu trữ cơ sở dữ liệu SQLite & Quản lý tập tin ảnh snapshot trên ổ đĩa
- Hệ thống tác vụ ngầm tự động dọn dẹp (Background Cron Job với APScheduler) dọn ảnh sau 24h
- Bảng điều khiển Giám thị (Proctor Dashboard) cập nhật theo thời gian thực

Danh sách API Endpoints:
  POST   /api/violations              — Nhận bản tin vi phạm + ảnh snapshot Base64 từ máy thí sinh (KHÔNG cần token)
  GET    /api/violations              — [Cần token giám thị] Lấy danh sách vi phạm có phân trang, lọc theo thí sinh / loại vi phạm
  GET    /api/students                — [Cần token giám thị] Danh sách "thư mục sinh viên" (mã SV, họ tên, tổng số vi phạm/ảnh)
  GET    /api/violations/stats        — [Cần token giám thị] Cung cấp số liệu thống kê tổng hợp cho bảng điều khiển giám thị
  DELETE /api/violations/all          — [Cần token giám thị] Xóa toàn bộ dữ liệu vi phạm và tập tin ảnh bằng chứng
  DELETE /api/violations/{id}/image   — [Cần token giám thị] Xóa thủ công tập tin ảnh của một bản ghi vi phạm (trước hạn 24h)
  GET    /api/snapshots/{folder}/{filename} — [Cần token giám thị] Phục vụ ảnh bằng chứng theo thư mục sinh viên (KHÔNG còn public)
  GET    /health                      — Kiểm tra trạng thái hoạt động của máy chủ (Health check)

  Module Đề thi — Chấm điểm — Xuất kết quả (chi tiết xem exams_router.py và
  tài liệu "Dac_Ta_Bo_Sung_Module_De_Thi.docx"):
  POST   /api/exams/upload                     — [GV] Upload file .xlsx/.docx, tạo đề thi DRAFT
  GET    /api/exams                            — [GV] Danh sách đề thi
  GET    /api/exams/{id}                       — [GV] Chi tiết đề thi (kèm đáp án đúng)
  POST   /api/exams/{id}/publish               — [GV] Công bố đề thi (DRAFT -> PUBLISHED)
  DELETE /api/exams/{id}                       — [GV] Xóa đề thi (chỉ khi chưa ai nộp bài)
  GET    /api/exams/code/{exam_code}/take      — [SV] Lấy đề để làm bài (KHÔNG kèm đáp án đúng)
  POST   /api/exams/code/{exam_code}/submit    — [SV] Nộp bài — chấm điểm tự động ngay lập tức
  GET    /api/exams/{id}/results               — [GV] Bảng điểm toàn bộ SV đã nộp, kèm số lần vi phạm
  GET    /api/exams/{id}/export                — [GV] Xuất file .xlsx bảng điểm

Xác thực (Auth):
  Toàn bộ endpoint dành cho Giám thị yêu cầu 1 token cố định, cấu hình qua biến môi trường
  PROCTOR_API_TOKEN. Client gửi token qua header "X-Proctor-Token" (cho các API JSON) hoặc
  qua query string "?token=" (cho ảnh, vì thẻ <img> không gửi được custom header).
  Đây là cơ chế xác thực đơn giản (shared secret) phù hợp quy mô đồ án — KHÔNG thay thế
  cho hệ thống đăng nhập/JWT đầy đủ trong sản phẩm thực tế.

Lệnh khởi chạy máy chủ:
  Tạo máy ảo:  python -m venv venv
  Kích hoạt máy ảo (Windows): .venv\\Scripts\\activate
  uvicorn main:app --reload --host 0.0.0.0 --port 8000

Cấu hình token giám thị (bắt buộc đổi trước khi demo/triển khai thật):
  Cách 1 — Khuyến nghị cho demo đồ án (chỉ cần đặt 1 lần, không cần export lại mỗi lần chạy):
    Tạo file "backend/.env" (xem "backend/.env.example") với nội dung:
      PROCTOR_API_TOKEN=chuoi-bi-mat-cua-ban
    File .env được tự động đọc mỗi khi chạy uvicorn — không cần set biến môi trường thủ công nữa.
  Cách 2 — Đặt biến môi trường thủ công cho từng phiên terminal:
    # Windows (PowerShell):  $env:PROCTOR_API_TOKEN = "ma-token-cua-ban"
    # Linux/macOS:           export PROCTOR_API_TOKEN="ma-token-cua-ban"
"""

import base64
import logging
import os
import re
import shutil
import uuid
from dotenv import load_dotenv
# Nạp biến môi trường từ file backend/.env (nếu có) — nhờ vậy chỉ cần cấu hình
# PROCTOR_API_TOKEN một lần trong file, không phải "export" lại mỗi lần mở terminal mới.
load_dotenv()

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, desc, func
from sqlalchemy.orm import Session

from auth import PROCTOR_API_TOKEN, USING_GENERATED_TOKEN, verify_proctor_token
from database import Violation, get_db, init_db
from exams_router import router as exams_router
from scheduler import shutdown_scheduler, start_scheduler

# ──────────────────────────────────────────────────────────
# CẤU HÌNH GHI NHẬT KÝ HỆ THỐNG (LOGGING CONFIGURATION)
# ──────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("edushield")

# ──────────────────────────────────────────────────────────
# CÁC HẰNG SỐ CẤU HÌNH (CONSTANTS)
# ──────────────────────────────────────────────────────────

# Đường dẫn tuyệt đối tới thư mục lưu trữ ảnh chụp bằng chứng vi phạm
SNAPSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")

# Tập hợp các loại hành vi vi phạm hợp lệ được hệ thống AI và Lockdown chấp nhận
VALID_VIOLATION_TYPES = {
    "NO_FACE",          # Không phát hiện khuôn mặt thí sinh trước camera
    "TURNING_HEAD",      # Thí sinh quay mặt sang trái/phải quá lâu (> 3.6s)
    "PHONE_DETECTED",   # Phát hiện đối tượng thiết bị di động (cell phone)
    "MULTIPLE_FACES",   # Phát hiện nhiều hơn 1 người trong khung hình
    "CAMERA_BLOCKED",   # Camera bị che mờ hoặc phòng thi không đủ ánh sáng
    "TAB_SWITCH",       # Thí sinh chuyển sang tab trình duyệt khác
    "WINDOW_BLUR",      # Cửa sổ bài thi bị mất tiêu điểm (mất focus)
    "FULLSCREEN_EXIT",  # Thí sinh cố tình thoát khỏi chế độ toàn màn hình
}

# Chỉ cho phép các ký tự an toàn trong tên thư mục sinh viên (chống path traversal / ký tự lạ)
_SAFE_FOLDER_CHARS = re.compile(r"[^A-Za-z0-9_-]+")


def sanitize_student_folder(student_id: str) -> str:
    """
    Chuẩn hóa mã sinh viên thành tên thư mục an toàn trên hệ thống file.
    Mỗi sinh viên có 1 thư mục riêng trong snapshots/, đặt tên theo mã SV đã làm sạch:
    ảnh vi phạm của SV nào sẽ nằm gọn trong thư mục của SV đó — dễ tra cứu, dễ dọn dẹp.
    """
    cleaned = _SAFE_FOLDER_CHARS.sub("_", (student_id or "").strip())
    cleaned = cleaned.strip("._-")[:50]
    return cleaned or "UNKNOWN"


# ──────────────────────────────────────────────────────────
# XÁC THỰC GIÁM THỊ (SHARED-SECRET TOKEN AUTH)
# ──────────────────────────────────────────────────────────
# Đã chuyển sang module dùng chung backend/auth.py — để CẢ module Giám sát (violations)
# VÀ module Đề thi (exams_router) đều xác thực bằng đúng 1 token duy nhất. Trước đây main.py
# tự định nghĩa 1 bản verify_proctor_token() RIÊNG, dẫn tới rủi ro: nếu không đặt biến môi
# trường PROCTOR_API_TOKEN, mỗi module tự sinh token ngẫu nhiên KHÁC NHAU khi khởi động,
# khiến giám thị đăng nhập được module này nhưng bị từ chối ở module kia.
# PROCTOR_API_TOKEN, USING_GENERATED_TOKEN, verify_proctor_token được import từ auth.py ở trên.


# ──────────────────────────────────────────────────────────
# ĐỊNH NGHĨA CÁC LỚP MẪU DỮ LIỆU (PYDANTIC SCHEMAS)
# ──────────────────────────────────────────────────────────

class ViolationCreate(BaseModel):
    """
    Lớp dữ liệu nhận vào (Request Body) cho API POST /api/violations
    Được gửi tự động từ Client (StudentExam) khi phát hiện hành vi gian lận.
    """
    student_id: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Mã định danh của thí sinh (VD: SV001)",
        examples=["SV001"],
    )
    student_name: Optional[str] = Field(
        default=None,
        max_length=150,
        description="Họ và tên thí sinh (do thí sinh tự nhập lúc đăng nhập, có thể để trống)",
        examples=["Nguyễn Văn A"],
    )
    violation_type: str = Field(
        ...,
        description="Loại vi phạm thuộc tập VALID_VIOLATION_TYPES",
        examples=["NO_FACE"],
    )
    captured_at: str = Field(
        ...,
        description="Thời điểm phát hiện vi phạm định dạng chuẩn ISO 8601",
        examples=["2026-09-04T10:00:00.000Z"],
    )
    image_base64: Optional[str] = Field(
        default=None,
        description="Chuỗi Base64 mã hóa ảnh chụp JPEG tại thời điểm vi phạm (hỗ trợ cả prefix data:image/jpeg;base64,)",
    )


class ViolationResponse(BaseModel):
    """
    Lớp dữ liệu phản hồi (Response Model) đại diện cho một bản ghi vi phạm
    Được trả về cho Client hoặc hiển thị trên giao diện Giám thị (Proctor Dashboard).
    """
    id: int
    student_id: str
    student_name: Optional[str] = None
    violation_type: str
    captured_at: Optional[str]
    image_url: Optional[str]
    created_at: Optional[str]


class StatsResponse(BaseModel):
    """
    Lớp dữ liệu phản hồi cho API thống kê tổng hợp GET /api/violations/stats
    Phục vụ trực quan hóa các chỉ số quan trọng trên bảng điều khiển giám sát.
    """
    total_violations: int
    total_with_images: int
    by_type: dict
    by_student: dict


class StudentSummary(BaseModel):
    """
    Đại diện cho 1 "thư mục sinh viên" trên giao diện Giám thị: gom toàn bộ vi phạm
    của cùng 1 student_id lại thành 1 hàng tổng hợp, thay vì liệt kê phẳng theo thời gian.
    """
    student_id: str
    student_name: Optional[str] = None
    violation_count: int
    image_count: int
    latest_violation_at: Optional[str] = None


# ──────────────────────────────────────────────────────────
# QUẢN LÝ VÒNG ĐỜI ỨNG DỤNG (APPLICATION LIFESPAN)
# ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Hàm quản lý vòng đời ứng dụng FastAPI (thay thế cho on_event startup và shutdown cũ).
    - Khởi động: Tạo thư mục lưu trữ ảnh, khởi tạo các bảng SQLite và kích hoạt Cron Job APScheduler.
    - Tắt máy chủ: Dừng an toàn bộ lập lịch tiến trình ngầm và giải phóng tài nguyên.
    """
    # ── GIAI ĐOẠN KHỞI ĐỘNG (STARTUP) ──
    logger.info("=" * 60)
    logger.info("EduShield AI Backend v3.0 — Đang khởi động hệ thống...")
    logger.info("=" * 60)

    # 1. Kiểm tra và tạo thư mục snapshots lưu ảnh bằng chứng
    try:
        os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
        logger.info("Thư mục lưu trữ ảnh snapshot đã sẵn sàng: %s", SNAPSHOTS_DIR)
    except OSError as exc:
        logger.error("Không thể tạo thư mục lưu trữ ảnh snapshot: %s", exc)
        raise

    # 2. Khởi tạo cơ sở dữ liệu SQLite và các bảng liên quan
    init_db()

    # 3. Kích hoạt bộ lập lịch tác vụ tự động dọn dẹp ảnh APScheduler (chạy mỗi 30 phút)
    start_scheduler()

    # 4. Cảnh báo/thông báo token xác thực giám thị
    if USING_GENERATED_TOKEN:
        logger.warning("=" * 60)
        logger.warning("KHÔNG tìm thấy biến môi trường PROCTOR_API_TOKEN.")
        logger.warning("Đã tự sinh 1 token TẠM THỜI cho phiên chạy này (sẽ đổi khi restart):")
        logger.warning("  PROCTOR_API_TOKEN = %s", PROCTOR_API_TOKEN)
        logger.warning("Giám thị dùng token này để đăng nhập Dashboard.")
        logger.warning("Để dùng token cố định, đặt biến môi trường PROCTOR_API_TOKEN trước khi chạy.")
        logger.warning("=" * 60)
    else:
        logger.info("Đã nạp PROCTOR_API_TOKEN từ biến môi trường.")

    logger.info("Toàn bộ dịch vụ đã kích hoạt thành công. Sẵn sàng tiếp nhận bản tin vi phạm.")
    logger.info("=" * 60)

    yield  # Ứng dụng hoạt động và tiếp nhận các yêu cầu HTTP

    # ── GIAI ĐOẠN DỪNG HỆ THỐNG (SHUTDOWN) ──
    logger.info("Đang tiến hành tắt dịch vụ EduShield AI Backend...")
    shutdown_scheduler()
    logger.info("Hệ thống đã dừng an toàn.")


# ──────────────────────────────────────────────────────────
# KHỞI TẠO ỨNG DỤNG FASTAPI & CẤU HÌNH MIDDLEWARE
# ──────────────────────────────────────────────────────────

app = FastAPI(
    title="EduShield AI Proctoring Engine",
    description="Hệ thống tiếp nhận, xử lý vi phạm thi trực tuyến với lưu trữ SQLite và tự động dọn dẹp",
    version="3.0.0",
    lifespan=lifespan,
)

# Cấu hình CORS cho phép ứng dụng Frontend (React Vite) kết nối mà không bị chặn
# Lưu ý: allow_credentials=False vì hệ thống xác thực bằng token qua header/query,
# KHÔNG dùng cookie — kết hợp allow_origins="*" với allow_credentials=True là rủi ro bảo mật.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gắn toàn bộ endpoint của module Đề thi (Upload — Chấm điểm — Xuất kết quả) vào ứng dụng chính.
# Router này định nghĩa sẵn prefix "/api/exams" nên các route thực tế sẽ là /api/exams/..., /api/exams/upload, v.v.
app.include_router(exams_router)

os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
# LƯU Ý: KHÔNG mount /snapshots làm static files công khai nữa (đây từng là lỗ hổng bảo mật —
# bất kỳ ai biết/đoán tên file đều xem được ảnh sinh viên mà không cần xác thực).
# Ảnh giờ được phục vụ qua endpoint /api/snapshots/{filename} có xác thực token, xem bên dưới.


# ──────────────────────────────────────────────────────────
# CÁC HÀM TIỆN ÍCH HỖ TRỢ (HELPER FUNCTIONS)
# ──────────────────────────────────────────────────────────

def decode_and_save_image(image_base64: str, student_id: str) -> str:
    """
    Chức năng: Giải mã chuỗi Base64 và ghi thành file ảnh JPEG vào thư mục riêng của từng
    sinh viên: snapshots/{mã_sv_đã_làm_sạch}/violation_...jpg — thay vì đổ chung 1 thư mục
    phẳng như trước (rất khó tra cứu khi có nhiều thí sinh).

    Tham số:
        image_base64: Chuỗi dữ liệu ảnh Base64 từ canvas (có hoặc không có tiền tố Data URL).
        student_id: Mã sinh viên, dùng để xác định/tạo thư mục lưu trữ riêng.

    Trả về:
        Đường dẫn tuyệt đối trên ổ đĩa tới file ảnh vừa được tạo.

    Ngoại lệ:
        ValueError: Nếu định dạng base64 sai hoặc không thể ghi file ra đĩa cứng.
    """
    try:
        # Tách bỏ tiền tố Data URL (VD: data:image/jpeg;base64,) nếu client gửi kèm
        raw_b64 = image_base64
        if "," in raw_b64:
            raw_b64 = raw_b64.split(",", 1)[1]

        # Giải mã chuỗi base64 thành mảng byte nhị phân
        image_bytes = base64.b64decode(raw_b64)

        # Kiểm tra tính toàn vẹn: Dữ liệu ảnh quá nhỏ thường là ảnh lỗi/rỗng
        if len(image_bytes) < 100:
            raise ValueError("Kích thước dữ liệu ảnh quá nhỏ — có thể dữ liệu bị lỗi")

        # Tạo/lấy thư mục riêng của sinh viên này trong snapshots/
        student_folder = sanitize_student_folder(student_id)
        student_dir = os.path.join(SNAPSHOTS_DIR, student_folder)
        os.makedirs(student_dir, exist_ok=True)

        # Tạo tên file duy nhất theo định dạng: violation_YYYYMMDD_HHMMSS_<uuid_ngan>.jpg
        filename = f"violation_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
        filepath = os.path.join(student_dir, filename)

        # Ghi luồng byte nhị phân xuống tệp tin
        with open(filepath, "wb") as f:
            f.write(image_bytes)

        logger.debug("Đã lưu ảnh snapshot: %s/%s (%d bytes)", student_folder, filename, len(image_bytes))
        return filepath

    except base64.binascii.Error as exc:
        raise ValueError(f"Chuỗi Base64 không hợp lệ: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Không thể ghi file ảnh xuống đĩa cứng: {exc}") from exc


def parse_captured_at(captured_at_str: str) -> datetime:
    """
    Chức năng: Chuyển đổi chuỗi thời gian ISO 8601 từ client thành đối tượng datetime UTC có timezone.

    Hỗ trợ các định dạng thời gian thông dụng:
      - '2026-09-04T10:00:00.000Z'
      - '2026-09-04T10:00:00Z'
      - '2026-09-04T10:00:00+07:00'
    """
    try:
        dt = datetime.fromisoformat(captured_at_str.replace("Z", "+00:00"))
        # Đảm bảo đối tượng luôn gắn thông tin múi giờ UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Định dạng thời gian không hợp lệ: {captured_at_str}") from exc


# ──────────────────────────────────────────────────────────
# DANH SÁCH CÁC API ENDPOINTS
# ──────────────────────────────────────────────────────────

@app.post("/api/violations", response_model=ViolationResponse, status_code=201)
def create_violation(payload: ViolationCreate, db: Session = Depends(get_db)):
    """
    API tiếp nhận bản tin ghi nhận vi phạm và ảnh bằng chứng từ phía phòng thi Sinh viên.

    Quy trình xử lý (Flow):
      1. Kiểm tra tính hợp lệ của loại vi phạm (violation_type)
      2. Chuyển đổi nhãn thời gian vi phạm (captured_at) sang chuẩn UTC
      3. Giải mã chuỗi image_base64 và lưu file ảnh tĩnh vào thư mục snapshots/
      4. Tạo bản ghi mới trong bảng violations của SQLite (chỉ lưu đường dẫn file, không lưu binary)
      5. Phản hồi thông tin bản ghi vừa tạo về cho client
    """
    try:
        # 1. Kiểm tra loại vi phạm
        if payload.violation_type not in VALID_VIOLATION_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Loại vi phạm không hợp lệ: '{payload.violation_type}'. "
                       f"Các loại hợp lệ: {', '.join(sorted(VALID_VIOLATION_TYPES))}",
            )

        # 2. Phân tích chuỗi thời gian
        try:
            captured_dt = parse_captured_at(payload.captured_at)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        # 3. Giải mã và lưu tập tin ảnh snapshot (nếu có kèm theo) — vào thư mục riêng của SV này
        image_path = None
        if payload.image_base64:
            try:
                image_path = decode_and_save_image(payload.image_base64, payload.student_id)
            except ValueError as exc:
                logger.warning(
                    "Lỗi giải mã/lưu ảnh của thí sinh %s: %s",
                    payload.student_id,
                    exc,
                )
                # Tiếp tục ghi nhận log kể cả khi lưu ảnh gặp lỗi để không làm mất bằng chứng vi phạm

        # 4. Lưu bản ghi vào cơ sở dữ liệu SQLite
        violation = Violation(
            student_id=payload.student_id,
            student_name=(payload.student_name or "").strip() or None,
            violation_type=payload.violation_type,
            captured_at=captured_dt,
            image_path=image_path,
            created_at=datetime.now(timezone.utc),
        )
        db.add(violation)
        db.commit()
        db.refresh(violation)

        logger.info(
            "Đã ghi nhận vi phạm: id=%d, sinh_vien=%s, loai=%s, co_anh=%s",
            violation.id,
            violation.student_id,
            violation.violation_type,
            "CÓ" if image_path else "KHÔNG",
        )

        return violation.to_dict()

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Lỗi khi tạo bản ghi vi phạm: %s", exc, exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail="Lỗi nội bộ máy chủ") from exc


@app.get("/api/violations", response_model=list[ViolationResponse])
def list_violations(
    student_id: Optional[str] = Query(default=None, description="Lọc theo mã định danh sinh viên"),
    violation_type: Optional[str] = Query(default=None, description="Lọc theo loại hành vi vi phạm"),
    limit: int = Query(default=200, ge=1, le=1000, description="Số lượng bản ghi tối đa cần lấy"),
    offset: int = Query(default=0, ge=0, description="Vị trí bắt đầu lấy dữ liệu phục vụ phân trang"),
    db: Session = Depends(get_db),
    _auth: None = Depends(verify_proctor_token),
):
    """
    [Cần token Giám thị] API truy vấn danh sách vi phạm phục vụ giao diện Bảng điều khiển Giám thị.

    Hỗ trợ các tính năng:
      - Bộ lọc theo mã sinh viên (student_id)
      - Bộ lọc theo chủng loại vi phạm (violation_type)
      - Cơ chế phân trang (Pagination với limit và offset)
      - Tự động sắp xếp bản ghi mới nhất lên đầu danh sách (DESC theo captured_at)
    """
    try:
        query = db.query(Violation)

        # Áp dụng bộ lọc sinh viên nếu có
        if student_id:
            query = query.filter(Violation.student_id == student_id)

        # Áp dụng bộ lọc loại vi phạm nếu có
        if violation_type:
            query = query.filter(Violation.violation_type == violation_type)

        # Sắp xếp theo thời gian mới nhất và áp dụng phân trang
        violations = (
            query
            .order_by(desc(Violation.captured_at))
            .offset(offset)
            .limit(limit)
            .all()
        )

        return [v.to_dict() for v in violations]

    except Exception as exc:
        logger.error("Lỗi khi truy vấn danh sách vi phạm: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi nội bộ máy chủ") from exc


@app.get("/api/students", response_model=list[StudentSummary])
def list_students(db: Session = Depends(get_db), _auth: None = Depends(verify_proctor_token)):
    """
    [Cần token Giám thị] API tổng hợp danh sách "thư mục sinh viên" — mỗi sinh viên đã từng
    có vi phạm sẽ xuất hiện đúng 1 lần kèm tổng số vi phạm/ảnh còn lại, phục vụ giao diện
    Dashboard hiển thị dạng thư mục (folder theo mã SV + họ tên) thay vì bảng phẳng.

    Sắp xếp theo thời điểm vi phạm gần nhất (sinh viên mới vi phạm sẽ hiện lên đầu).
    """
    try:
        rows = (
            db.query(
                Violation.student_id,
                func.max(Violation.student_name),
                func.count(Violation.id),
                func.sum(case((Violation.image_path.isnot(None), 1), else_=0)),
                func.max(Violation.captured_at),
            )
            .group_by(Violation.student_id)
            .order_by(desc(func.max(Violation.captured_at)))
            .all()
        )

        return [
            {
                "student_id": student_id,
                "student_name": student_name,
                "violation_count": violation_count,
                "image_count": int(image_count or 0),
                "latest_violation_at": latest_at.isoformat() if latest_at else None,
            }
            for student_id, student_name, violation_count, image_count, latest_at in rows
        ]

    except Exception as exc:
        logger.error("Lỗi khi tổng hợp danh sách sinh viên: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi nội bộ máy chủ") from exc


@app.get("/api/violations/stats", response_model=StatsResponse)
def get_violation_stats(db: Session = Depends(get_db), _auth: None = Depends(verify_proctor_token)):
    """
    [Cần token Giám thị] API tổng hợp số liệu thống kê tình hình vi phạm của phòng thi.

    Dữ liệu trả về gồm:
      - total_violations: Tổng số lượt vi phạm được ghi nhận
      - total_with_images: Số lượt vi phạm còn lưu trữ ảnh bằng chứng
      - by_type: Bảng đếm số lượng theo từng phân loại vi phạm
      - by_student: Bảng đếm số lượng vi phạm của từng thí sinh
    """
    try:
        # Đếm tổng số vi phạm trong hệ thống
        total = db.query(func.count(Violation.id)).scalar() or 0

        # Đếm số lượng vi phạm còn file ảnh bằng chứng
        total_with_images = (
            db.query(func.count(Violation.id))
            .filter(Violation.image_path.isnot(None))
            .scalar()
            or 0
        )

        # Thống kê gom nhóm theo loại vi phạm
        type_counts = (
            db.query(Violation.violation_type, func.count(Violation.id))
            .group_by(Violation.violation_type)
            .all()
        )
        by_type = {t: c for t, c in type_counts}

        # Thống kê gom nhóm theo sinh viên
        student_counts = (
            db.query(Violation.student_id, func.count(Violation.id))
            .group_by(Violation.student_id)
            .all()
        )
        by_student = {s: c for s, c in student_counts}

        return {
            "total_violations": total,
            "total_with_images": total_with_images,
            "by_type": by_type,
            "by_student": by_student,
        }

    except Exception as exc:
        logger.error("Lỗi khi lấy dữ liệu thống kê vi phạm: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi nội bộ máy chủ") from exc


@app.delete("/api/violations/all")
def delete_all_violations(db: Session = Depends(get_db), _auth: None = Depends(verify_proctor_token)):
    """
    [Cần token Giám thị] API xóa TOÀN BỘ dữ liệu vi phạm và các tập tin ảnh bằng chứng trên hệ thống.

    Quy trình thực hiện:
      1. Xóa toàn bộ các dòng dữ liệu trong bảng violations của SQLite
      2. Xóa sạch toàn bộ cây thư mục snapshots/ (mọi thư mục con theo từng sinh viên)
         rồi tạo lại thư mục gốc rỗng — đơn giản và triệt để hơn xóa từng file lẻ.
    """
    try:
        total_deleted = db.query(Violation).delete()
        db.commit()

        # Xóa sạch toàn bộ cây thư mục ảnh (mọi thư mục con theo từng SV) rồi tạo lại thư mục gốc
        deleted_files = 0
        try:
            if os.path.isdir(SNAPSHOTS_DIR):
                deleted_files = sum(len(files) for _, _, files in os.walk(SNAPSHOTS_DIR))
                shutil.rmtree(SNAPSHOTS_DIR)
            os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
        except OSError as exc:
            logger.warning("Không thể xóa sạch thư mục snapshots/: %s", exc)

        logger.info(
            "Xóa toàn bộ vi phạm: Đã xóa %d bản ghi, %d file ảnh trong toàn bộ thư mục snapshots/",
            total_deleted,
            deleted_files,
        )

        return {
            "message": "Đã xóa toàn bộ dữ liệu vi phạm thành công",
            "total_deleted": total_deleted,
            "files_deleted": deleted_files,
            "files_failed": 0,
        }

    except Exception as exc:
        logger.error("Lỗi khi xóa toàn bộ vi phạm: %s", exc, exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail="Lỗi nội bộ máy chủ") from exc


@app.delete("/api/violations/{violation_id}/image")
def delete_violation_image(
    violation_id: int,
    db: Session = Depends(get_db),
    _auth: None = Depends(verify_proctor_token),
):
    """
    [Cần token Giám thị] API xóa tập tin ảnh bằng chứng của một bản ghi vi phạm cụ thể (Xóa thủ công sớm).

    Ý nghĩa:
      Khi Giám thị nhấn nút "Xóa ảnh" trên bảng điều khiển, file ảnh vật lý trên đĩa sẽ bị xóa ngay
      và trường image_path trong cơ sở dữ liệu được đặt thành NULL.
      Lưu ý: Bản ghi nhật ký vi phạm (thời gian, sinh viên, loại lỗi) VẪN ĐƯỢC BẢO LƯU trong DB.
    """
    try:
        violation = db.query(Violation).filter(Violation.id == violation_id).first()

        if not violation:
            raise HTTPException(
                status_code=404,
                detail=f"Không tìm thấy bản ghi vi phạm với id={violation_id}",
            )

        if not violation.image_path:
            return {
                "message": "Ảnh bằng chứng đã bị xóa từ trước hoặc không đính kèm ảnh",
                "violation_id": violation_id,
            }

        # Xóa file ảnh vật lý trên ổ đĩa
        deleted_file = False
        if os.path.isfile(violation.image_path):
            try:
                os.remove(violation.image_path)
                deleted_file = True
                logger.info(
                    "Giám thị đã xóa thủ công ảnh snapshot: %s (violation_id=%d)",
                    violation.image_path,
                    violation_id,
                )
            except OSError as exc:
                logger.warning(
                    "Không thể xóa file ảnh %s: %s",
                    violation.image_path,
                    exc,
                )

        # Cập nhật trường image_path = NULL trong CSDL
        violation.image_path = None
        db.commit()

        return {
            "message": "Đã xóa ảnh bằng chứng thành công" if deleted_file else "Đã xóa liên kết ảnh (file không tồn tại trên đĩa)",
            "violation_id": violation_id,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Lỗi khi xóa ảnh của vi phạm id=%d: %s",
            violation_id,
            exc,
            exc_info=True,
        )
        db.rollback()
        raise HTTPException(status_code=500, detail="Lỗi nội bộ máy chủ") from exc


@app.get("/api/snapshots/{student_folder}/{filename}")
def get_snapshot_image(
    student_folder: str,
    filename: str,
    _auth: None = Depends(verify_proctor_token),
):
    """
    [Cần token Giám thị] API phục vụ tập tin ảnh snapshot theo cấu trúc thư mục riêng từng
    sinh viên (snapshots/{student_folder}/{filename}) — thay thế cho việc mount thư mục
    /snapshots công khai trước đây (lỗ hổng: ai cũng xem được ảnh nếu biết/đoán tên file).

    Bảo vệ chống Path Traversal: mỗi phần của đường dẫn chỉ được chứa tên thuần
    (không '/', '\\', hay '..'), nhờ FastAPI tách riêng 2 path param nên không thể
    "leo" ra ngoài thư mục snapshots/.
    """
    safe_folder = os.path.basename(student_folder)
    safe_name = os.path.basename(filename)
    if safe_folder != student_folder or safe_name != filename or ".." in student_folder or ".." in filename:
        raise HTTPException(status_code=400, detail="Đường dẫn tập tin không hợp lệ")

    filepath = os.path.join(SNAPSHOTS_DIR, safe_folder, safe_name)
    if not os.path.isfile(filepath):
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy ảnh (có thể đã bị xóa tự động sau 24h hoặc do giám thị xóa sớm)",
        )

    return FileResponse(filepath, media_type="image/jpeg")


# ──────────────────────────────────────────────────────────
# KIỂM TRA TRẠNG THÁI HỆ THỐNG (HEALTH CHECK ENDPOINT)
# ──────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    """Endpoint kiểm tra tình trạng sống (liveness probe) của máy chủ backend."""
    return {
        "status": "ok",
        "engine": "EduShield AI Proctoring",
        "version": "3.0.0",
        "architecture": "Client-side AI Detection + Event-driven Logging",
    }


# ──────────────────────────────────────────────────────────
# PHỤC VỤ GIAO DIỆN WEB (frontend/dist) — dùng cho web PC và web/PWA trên điện thoại
# ──────────────────────────────────────────────────────────
# Sau khi chạy `npm run build` trong thư mục frontend, FastAPI phục vụ luôn giao diện ở cùng
# địa chỉ với API. Nhờ vậy chỉ cần MỘT tunnel HTTPS (camera trên điện thoại bắt buộc HTTPS)
# và không còn vướng proxy của Vite. Nếu chưa build thì bỏ qua — chạy `npm run dev` như trước.
# Phải đặt SAU MỌI route /api và /health để route catch-all bên dưới không nuốt chúng.

FRONTEND_DIST_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist"
)
_FRONTEND_INDEX = os.path.join(FRONTEND_DIST_DIR, "index.html")

# Đặt Content-Type tường minh: trên một số máy Windows, registry map .js thành text/plain
# khiến trình duyệt từ chối nạp module script.
_STATIC_MEDIA_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".webmanifest": "application/manifest+json",
    ".json": "application/json",
    ".wasm": "application/wasm",
    ".html": "text/html",
}

if os.path.isfile(_FRONTEND_INDEX):
    _dist_root = os.path.realpath(FRONTEND_DIST_DIR)

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str):
        """Trả file tĩnh trong frontend/dist; đường dẫn không tồn tại rơi về index.html (SPA)."""
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Không tìm thấy")

        candidate = os.path.realpath(os.path.join(_dist_root, full_path))
        # Chống path traversal: file phải nằm trong frontend/dist
        if (
            full_path
            and candidate.startswith(_dist_root + os.sep)
            and os.path.isfile(candidate)
        ):
            ext = os.path.splitext(candidate)[1].lower()
            # Tên file trong /assets/ có mã băm nội dung nên cache lâu được; file khác luôn kiểm tra lại
            cache = (
                "public, max-age=31536000, immutable"
                if full_path.startswith("assets/")
                else "no-cache"
            )
            return FileResponse(
                candidate,
                media_type=_STATIC_MEDIA_TYPES.get(ext),
                headers={"Cache-Control": cache},
            )

        return FileResponse(
            _FRONTEND_INDEX,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )

    logger.info("Đã bật phục vụ giao diện web từ %s", FRONTEND_DIST_DIR)