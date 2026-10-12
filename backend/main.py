"""
Hệ thống Giám sát Thi Trực tuyến Thông minh EduShield AI — Backend Engine v3.0

Kiến trúc Hệ thống:
- Phát hiện AI phía Client (MediaPipe WebAssembly trên trình duyệt thí sinh)
- Cơ chế gửi bản tin hướng sự kiện (Event-driven Logging qua HTTPS RESTful API)
- Lưu trữ cơ sở dữ liệu SQLite & Quản lý tập tin ảnh snapshot trên ổ đĩa
- Hệ thống tác vụ ngầm tự động dọn dẹp (Background Cron Job với APScheduler) dọn ảnh sau 24h
- Bảng điều khiển Giám thị (Proctor Dashboard) cập nhật theo thời gian thực

Danh sách API Endpoints:
  POST   /api/violations              — Nhận bản tin vi phạm; yêu cầu phiên thi đã được duyệt
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
  GET    /api/exams/enrollments                — [GV] Yêu cầu vào thi, lọc theo môn/đề/trạng thái, kèm lịch sử vi phạm
  GET    /api/exams/{id}                       — [GV] Chi tiết đề thi (kèm đáp án đúng)
  POST   /api/exams/{id}/publish               — [GV] Công bố đề thi (DRAFT -> PUBLISHED)
  POST   /api/exams/{id}/close                 — [GV] Đóng đề thi
  DELETE /api/exams/{id}                       — [GV] Xóa đề thi (chỉ khi chưa ai nộp bài)
  GET    /api/exams/available                 — [Công khai] Danh sách môn và đề đang mở
  POST   /api/exams/{id}/join-request         — [SV] Xin vào thi, trả request_token
  GET    /api/exams/join-request/status       — [SV] Kiểm tra trạng thái qua X-Request-Token, cấp phiên một lần
  POST   /api/exams/join-request/cancel       — [SV] Hủy yêu cầu đang chờ
  POST   /api/exams/{id}/enrollments/approve-all — [GV] Duyệt toàn bộ yêu cầu chờ
  POST   /api/exams/{id}/enrollments/{enrollment_id}/approve — [GV] Duyệt một yêu cầu
  POST   /api/exams/{id}/enrollments/{enrollment_id}/reject  — [GV] Từ chối kèm lý do
  POST   /api/exams/{id}/enrollments/{enrollment_id}/revoke  — [GV] Thu hồi phiên thi
  GET    /api/exams/code/{exam_code}/take      — [SV đã duyệt] Lấy đề (KHÔNG kèm đáp án đúng)
  POST   /api/exams/code/{exam_code}/start     — [SV đã duyệt] Bắt đầu bài thi
  POST   /api/exams/code/{exam_code}/submit    — [SV đã duyệt] Nộp bài — chấm điểm tự động
  GET    /api/exams/{id}/results               — [GV] Bảng điểm toàn bộ SV đã nộp, kèm số lần vi phạm
  GET    /api/exams/{id}/export                — [GV] Xuất file .xlsx bảng điểm

Xác thực:
  Giảng viên đăng nhập bằng mã tài khoản và mật khẩu; mật khẩu và token phiên chỉ lưu dạng băm.
  Sinh viên khai báo mã định danh khi xin vào thi; sau đó mọi thao tác thi và vi phạm lấy
  danh tính từ phiên X-Exam-Session đã được giảng viên duyệt.

Lệnh khởi chạy máy chủ:
  Tạo máy ảo:  python -m venv venv
  Kích hoạt máy ảo (Windows): .venv\\Scripts\\activate
  uvicorn main:app --reload --host 0.0.0.0 --port 8000

Tạo tài khoản giảng viên:
  Chạy python backend\\create_teacher.py GV-2026 "Họ tên giảng viên";
  mật khẩu được nhập tương tác và không xuất hiện trong lịch sử dòng lệnh.
"""

import base64
import logging
import os
import re
import shutil
import threading
import uuid
from dotenv import load_dotenv
# Nạp các cấu hình backend tùy chọn từ file backend/.env.
load_dotenv()

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, desc, func
from sqlalchemy.orm import Session

import time
from typing import Dict, List, Optional

from auth import (
    check_login_rate_limit,
    create_teacher_session,
    extract_bearer_token,
    get_current_teacher,
    get_exam_session,
    hash_password,
    hash_token,
    normalize_teacher_code,
    record_login_failure,
    record_login_success,
    verify_password,
)
from database import (
    ExamEnrollment,
    Teacher,
    TeacherSession,
    Violation,
    get_db,
    init_db,
)
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

# Giới hạn kích thước ảnh snapshot và dung lượng đĩa
MAX_SNAPSHOT_SIZE_BYTES = 300 * 1024  # 300KB
MAX_BASE64_IMAGE_CHARS = 450 * 1024
MAX_SNAPSHOTS_STORAGE_BYTES = int(
    os.environ.get("MAX_SNAPSHOTS_STORAGE_BYTES", str(2 * 1024 * 1024 * 1024))
)
if MAX_SNAPSHOTS_STORAGE_BYTES <= 0:
    raise ValueError("MAX_SNAPSHOTS_STORAGE_BYTES must be a positive integer")
MAX_VIOLATIONS_PER_MINUTE = 30
MAX_VIOLATIONS_PER_SESSION = 600

# Bộ nhớ tạm rate limiting vi phạm theo lượt ghi danh (enrollment_id -> timestamps)
_violation_rate_window: Dict[int, List[float]] = {}
_violation_session_count: Dict[int, int] = {}
_violation_tracking_lock = threading.Lock()
_last_violation_tracking_cleanup = 0.0
VIOLATION_TRACKING_CLEANUP_INTERVAL_SECONDS = 300
_last_snapshots_size = 0
_last_snapshots_check_time = 0.0
_snapshots_storage_lock = threading.RLock()


def get_snapshots_dir_size(dir_path: str = SNAPSHOTS_DIR) -> int:
    """Tính tổng dung lượng (bytes) của toàn bộ thư mục snapshots."""
    total_size = 0
    if not os.path.exists(dir_path):
        return 0

    def raise_walk_error(exc: OSError) -> None:
        raise exc

    for root, _, files in os.walk(dir_path, onerror=raise_walk_error):
        for filename in files:
            total_size += os.path.getsize(os.path.join(root, filename))
    return total_size


def check_snapshots_quota_exceeded(additional_bytes: int = 0) -> bool:
    """Kiểm tra tổng dung lượng hiện tại cộng ảnh sắp lưu so với quota cấu hình."""
    global _last_snapshots_size, _last_snapshots_check_time
    now = time.time()
    with _snapshots_storage_lock:
        if now - _last_snapshots_check_time > 30.0:
            _last_snapshots_size = get_snapshots_dir_size(SNAPSHOTS_DIR)
            _last_snapshots_check_time = now
        return _last_snapshots_size + additional_bytes > MAX_SNAPSHOTS_STORAGE_BYTES


def _invalidate_snapshots_size_cache() -> None:
    global _last_snapshots_check_time
    with _snapshots_storage_lock:
        _last_snapshots_check_time = 0.0


def _consume_violation_quota(enrollment_id: int, db: Session) -> None:
    """Giới hạn vi phạm theo phiên và dọn trạng thái của các phiên không còn hoạt động."""
    global _last_violation_tracking_cleanup
    now = time.monotonic()
    with _violation_tracking_lock:
        if now - _last_violation_tracking_cleanup >= VIOLATION_TRACKING_CLEANUP_INTERVAL_SECONDS:
            active_ids = {
                row[0]
                for row in db.query(ExamEnrollment.id).filter(
                    ExamEnrollment.status == "APPROVED",
                    ExamEnrollment.session_token_issued.is_(True),
                ).all()
            }
            for tracked_id in tuple(_violation_rate_window):
                recent = [
                    timestamp
                    for timestamp in _violation_rate_window[tracked_id]
                    if now - timestamp < 60.0
                ]
                if recent and tracked_id in active_ids:
                    _violation_rate_window[tracked_id] = recent
                else:
                    _violation_rate_window.pop(tracked_id, None)
            for tracked_id in tuple(_violation_session_count):
                if tracked_id not in active_ids:
                    _violation_session_count.pop(tracked_id, None)
            _last_violation_tracking_cleanup = now

        recent_attempts = [
            timestamp
            for timestamp in _violation_rate_window.get(enrollment_id, [])
            if now - timestamp < 60.0
        ]
        if len(recent_attempts) >= MAX_VIOLATIONS_PER_MINUTE:
            _violation_rate_window[enrollment_id] = recent_attempts
            raise HTTPException(
                status_code=429,
                detail="Tần suất gửi vi phạm quá cao (tối đa 30 vi phạm/phút).",
            )
        total_count = _violation_session_count.get(enrollment_id, 0)
        if total_count >= MAX_VIOLATIONS_PER_SESSION:
            raise HTTPException(
                status_code=429,
                detail="Đã đạt số lượng vi phạm tối đa cho phép trong phiên thi (600 vi phạm).",
            )
        recent_attempts.append(now)
        _violation_rate_window[enrollment_id] = recent_attempts
        _violation_session_count[enrollment_id] = total_count + 1


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
# API giảng viên và router đề thi xác thực tập trung qua phiên TeacherSession.


# ──────────────────────────────────────────────────────────
# ĐỊNH NGHĨA CÁC LỚP MẪU DỮ LIỆU (PYDANTIC SCHEMAS)
# ──────────────────────────────────────────────────────────

class ViolationCreate(BaseModel):
    """
    Lớp dữ liệu nhận vào (Request Body) cho API POST /api/violations
    Được gửi từ StudentExam khi phát hiện hành vi gian lận; danh tính lấy từ phiên thi.
    """
    model_config = ConfigDict(extra="forbid")

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
    exam_id: Optional[int] = None
    enrollment_id: Optional[int] = None


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


class TeacherLoginRequest(BaseModel):
    """Lớp dữ liệu nhận vào khi Giảng viên đăng nhập."""
    teacher_code: str = Field(..., min_length=1, max_length=50, description="Mã giảng viên (VD: GV001)")
    password: str = Field(..., min_length=1, description="Mật khẩu tài khoản giảng viên")



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

# Cùng origin không cần CORS; chỉ mở các origin khác khi được cấu hình tường minh.
allowed_origins_raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
cors_origins = [origin.strip() for origin in allowed_origins_raw.split(",") if origin.strip()]
if "*" in cors_origins:
    raise ValueError("ALLOWED_ORIGINS không chấp nhận wildcard '*'; hãy khai báo origin cụ thể.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gắn toàn bộ endpoint của module Đề thi (Upload — Chấm điểm — Xuất kết quả) vào ứng dụng chính.
# Router này định nghĩa sẵn prefix "/api/exams" nên các route thực tế sẽ là /api/exams/..., /api/exams/upload, v.v.
app.include_router(exams_router)

# ──────────────────────────────────────────────────────────
# XÁC THỰC GIẢNG VIÊN (TEACHER AUTHENTICATION APIS)
# ──────────────────────────────────────────────────────────

@app.post("/api/auth/teacher/login")
def teacher_login(
    payload: TeacherLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Đăng nhập Giảng viên / Giám thị.
    Kiểm tra mã GV + mật khẩu, giới hạn 5 lần sai / phút, token hiệu lực 12 giờ.
    """
    client_ip = request.client.host if request.client else "127.0.0.1"
    check_login_rate_limit(client_ip)

    try:
        code = normalize_teacher_code(payload.teacher_code)
    except HTTPException:
        record_login_failure(client_ip)
        raise HTTPException(
            status_code=401,
            detail="Mã giảng viên hoặc mật khẩu không chính xác.",
        )
    teacher = db.query(Teacher).filter(Teacher.teacher_code == code).first()
    if not teacher or not verify_password(payload.password, teacher.password_salt, teacher.password_hash):
        record_login_failure(client_ip)
        raise HTTPException(
            status_code=401,
            detail="Mã giảng viên hoặc mật khẩu không chính xác.",
        )

    record_login_success(client_ip)
    if len(teacher.password_hash) != 128:
        teacher.password_hash, teacher.password_salt = hash_password(payload.password)
        db.commit()
    token, expires_at = create_teacher_session(db, teacher.id, ip=client_ip)
    logger.info("Giảng viên '%s' (%s) đã đăng nhập thành công từ IP %s", teacher.teacher_code, teacher.full_name, client_ip)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": (
            expires_at.replace(tzinfo=timezone.utc)
            if expires_at.tzinfo is None
            else expires_at.astimezone(timezone.utc)
        ).isoformat(),
        "teacher": teacher.to_dict(),
    }


@app.get("/api/auth/teacher/me")
def teacher_me(teacher: Teacher = Depends(get_current_teacher)):
    """Lấy thông tin Giảng viên đang đăng nhập qua token."""
    return {"teacher": teacher.to_dict()}


@app.post("/api/auth/teacher/logout")
def teacher_logout(
    authorization: Optional[str] = Header(default=None),
    teacher: Teacher = Depends(get_current_teacher),
    db: Session = Depends(get_db),
):
    """Đăng xuất: thu hồi phiên làm việc của Giảng viên."""
    raw_token = extract_bearer_token(authorization)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Thiếu phiên đăng nhập Giảng viên.")

    token_hash = hash_token(raw_token)
    deleted_count = (
        db.query(TeacherSession)
        .filter(
            TeacherSession.token_hash == token_hash,
            TeacherSession.teacher_id == teacher.id,
        )
        .delete()
    )
    if deleted_count:
        db.commit()
    return {"message": "Đã đăng xuất thành công."}


os.makedirs(SNAPSHOTS_DIR, exist_ok=True)

# LƯU Ý: KHÔNG mount /snapshots làm static files công khai nữa (đây từng là lỗ hổng bảo mật —
# bất kỳ ai biết/đoán tên file đều xem được ảnh sinh viên mà không cần xác thực).
# Ảnh giờ được phục vụ qua endpoint /api/snapshots/{filename} có xác thực token, xem bên dưới.


# ──────────────────────────────────────────────────────────
# CÁC HÀM TIỆN ÍCH HỖ TRỢ (HELPER FUNCTIONS)
# ──────────────────────────────────────────────────────────

def decode_and_save_image(image_base64: str, student_id: str) -> Optional[str]:
    """
    Xác thực kích thước chuỗi Base64 trước khi giải mã, rồi kiểm tra JPEG và quota.
    Trả None khi quota đầy để endpoint vẫn lưu metadata vi phạm mà không lưu ảnh.
    """
    if len(image_base64) > MAX_BASE64_IMAGE_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Chuỗi ảnh vượt quá giới hạn {MAX_BASE64_IMAGE_CHARS // 1024}KB.",
        )
    raw_b64 = image_base64.split(",", 1)[1] if "," in image_base64 else image_base64
    if len(raw_b64) > MAX_BASE64_IMAGE_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Chuỗi ảnh vượt quá giới hạn {MAX_BASE64_IMAGE_CHARS // 1024}KB.",
        )

    try:
        image_bytes = base64.b64decode(raw_b64, validate=True)
    except (base64.binascii.Error, ValueError) as exc:
        raise ValueError(f"Chuỗi Base64 không hợp lệ: {exc}") from exc

    if len(image_bytes) > MAX_SNAPSHOT_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Kích thước ảnh sau giải mã vượt quá giới hạn tối đa 300KB.",
        )
    if len(image_bytes) < 100:
        raise ValueError("Kích thước dữ liệu ảnh quá nhỏ — có thể dữ liệu bị lỗi")
    if image_bytes[:3] != b"\xff\xd8\xff":
        raise ValueError("Ảnh snapshot không đúng định dạng JPEG hợp lệ (thiếu SOI marker)")

    student_folder = sanitize_student_folder(student_id)
    student_dir = os.path.join(SNAPSHOTS_DIR, student_folder)
    filename = f"violation_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
    filepath = os.path.join(student_dir, filename)

    try:
        with _snapshots_storage_lock:
            if check_snapshots_quota_exceeded(len(image_bytes)):
                logger.warning(
                    "Thư mục snapshots đã đạt quota %d bytes. Ghi log vi phạm nhưng bỏ qua ảnh.",
                    MAX_SNAPSHOTS_STORAGE_BYTES,
                )
                return None
            os.makedirs(student_dir, exist_ok=True)
            with open(filepath, "wb") as image_file:
                image_file.write(image_bytes)
            global _last_snapshots_size
            _last_snapshots_size += len(image_bytes)
        logger.debug(
            "Đã lưu ảnh snapshot: %s/%s (%d bytes)",
            student_folder,
            filename,
            len(image_bytes),
        )
        return filepath
    except OSError:
        try:
            os.remove(filepath)
        except FileNotFoundError:
            pass
        except OSError as cleanup_error:
            logger.error("Không thể dọn ảnh ghi dở %s: %s", filepath, cleanup_error)
        raise


def parse_captured_at(captured_at_str: str) -> datetime:
    """
    Chức năng: Chuyển đổi chuỗi thời gian ISO 8601 từ client thành đối tượng datetime UTC có timezone.
    """
    try:
        dt = datetime.fromisoformat(captured_at_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Định dạng thời gian không hợp lệ: {captured_at_str}") from exc


# ──────────────────────────────────────────────────────────
# DANH SÁCH CÁC API ENDPOINTS
# ──────────────────────────────────────────────────────────

@app.post("/api/violations", response_model=ViolationResponse, status_code=201)
def create_violation(
    payload: ViolationCreate,
    enrollment: ExamEnrollment = Depends(get_exam_session),
    db: Session = Depends(get_db),
):
    """
    API tiếp nhận bản tin ghi nhận vi phạm và ảnh bằng chứng từ phía phòng thi Sinh viên.
    Yêu cầu header X-Exam-Session đã được phê duyệt, kiểm tra rate limit, lệch thời gian và ảnh snapshot.
    """
    try:
        clean_student_id = enrollment.student_id

        # Rate limit gắn với enrollment đang được xác thực, không nhận ID từ body.
        _consume_violation_quota(enrollment.id, db)

        # 3. Kiểm tra loại vi phạm
        if payload.violation_type not in VALID_VIOLATION_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Loại vi phạm không hợp lệ: '{payload.violation_type}'. "
                       f"Các loại hợp lệ: {', '.join(sorted(VALID_VIOLATION_TYPES))}",
            )

        # 4. Phân tích chuỗi thời gian & kiểm tra lệch không quá 5 phút (300 giây)
        try:
            captured_dt = parse_captured_at(payload.captured_at)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        now_utc = datetime.now(timezone.utc)
        time_diff = abs((now_utc - captured_dt).total_seconds())
        if time_diff > 300:
            raise HTTPException(
                status_code=400,
                detail=f"Thời điểm ghi nhận vi phạm lệch quá 5 phút so với máy chủ ({int(time_diff)} giây).",
            )

        # 5. Giải mã và lưu ảnh snapshot (kiểm tra 300KB, JPEG magic bytes, quota 2GB)
        image_path = None
        if payload.image_base64:
            try:
                image_path = decode_and_save_image(payload.image_base64, clean_student_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        # 6. Lưu bản ghi vào cơ sở dữ liệu SQLite
        violation = Violation(
            student_id=clean_student_id,
            student_name=enrollment.student_name,
            violation_type=payload.violation_type,
            captured_at=captured_dt,
            image_path=image_path,
            created_at=now_utc,
            exam_id=enrollment.exam_id,
            enrollment_id=enrollment.id,
        )
        db.add(violation)
        db.commit()
        db.refresh(violation)

        logger.info(
            "Đã ghi nhận vi phạm: id=%d, sinh_vien=%s, exam_id=%s, loai=%s, co_anh=%s",
            violation.id,
            violation.student_id,
            violation.exam_id,
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
    _teacher: Teacher = Depends(get_current_teacher),
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
def list_students(db: Session = Depends(get_db), _teacher: Teacher = Depends(get_current_teacher)):
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
def get_violation_stats(db: Session = Depends(get_db), _teacher: Teacher = Depends(get_current_teacher)):
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
def delete_all_violations(db: Session = Depends(get_db), _teacher: Teacher = Depends(get_current_teacher)):
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
            _invalidate_snapshots_size_cache()
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
    _teacher: Teacher = Depends(get_current_teacher),
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
                _invalidate_snapshots_size_cache()
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
    _teacher: Teacher = Depends(get_current_teacher),
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