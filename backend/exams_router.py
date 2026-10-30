"""
EduShield AI — Module Đề thi: Upload — Quản lý — Làm bài — Chấm điểm tự động — Xuất kết quả

Toàn bộ endpoint của module này được đặc tả chi tiết tại tài liệu
"Dac_Ta_Bo_Sung_Module_De_Thi.docx" (Chương 3, 5, 7, 9). File này chia làm 3 phần rõ rệt:

  PHẦN A — Quản lý đề thi (dành cho Giảng viên, cần token):
      POST   /api/exams/upload            Upload file .xlsx/.docx, đọc & validate, tạo đề DRAFT
      GET    /api/exams                   Danh sách toàn bộ đề thi
      GET    /api/exams/{id}               Chi tiết 1 đề (kèm đáp án đúng)
      POST   /api/exams/{id}/publish       Công bố đề thi (DRAFT -> PUBLISHED)
      DELETE /api/exams/{id}               Xóa đề thi (chỉ khi chưa có ai nộp bài)

  PHẦN B — Sinh viên làm bài (bắt buộc có phiên X-Exam-Session đã được duyệt):
      GET    /api/exams/code/{exam_code}/take    Lấy đề để làm bài (KHÔNG kèm đáp án đúng)
      POST   /api/exams/code/{exam_code}/start   Bắt đầu và nhận thời gian còn lại
      POST   /api/exams/code/{exam_code}/submit  Nộp bài — chấm điểm tự động ngay lập tức

  PHẦN C — Kết quả & Xuất báo cáo (dành cho Giảng viên, cần token):
      GET    /api/exams/{id}/results       Bảng điểm toàn bộ SV đã nộp, kèm số lần vi phạm
      GET    /api/exams/{id}/export        Xuất file .xlsx bảng điểm
"""

import io
import logging
import os
import re
import secrets
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from auth import (
    get_current_teacher,
    get_exam_session,
    hash_token,
)
from database import (
    ENROLLMENT_STATUS_APPROVED,
    ENROLLMENT_STATUS_PENDING,
    ENROLLMENT_STATUS_REJECTED,
    ENROLLMENT_STATUS_REVOKED,
    Exam,
    ExamEnrollment,
    ExamStart,
    ExamSubmission,
    Question,
    SubmissionAnswer,
    Teacher,
    Violation,
    EXAM_STATUS_CLOSED,
    EXAM_STATUS_DRAFT,
    EXAM_STATUS_PUBLISHED,
    SUBMISSION_STATUS_AUTO_SUBMITTED,
    SUBMISSION_STATUS_SUBMITTED,
    get_db,
)
from exam_parser import MAX_QUESTIONS_PER_EXAM, parse_exam_file

logger = logging.getLogger("edushield.exams")

router = APIRouter(prefix="/api/exams", tags=["exams"])
AVAILABLE_EXAMS_RATE_LIMIT = 60
AVAILABLE_EXAMS_RATE_WINDOW_SECONDS = 60
_available_exams_requests: Dict[str, List[float]] = {}
_available_exams_rate_lock = threading.Lock()

ALLOWED_UPLOAD_EXTENSIONS = (".xlsx", ".docx")
MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024  # 5MB

# Regex mã sinh viên (mặc định chấp nhận SV001, SV-2151220053...)
STUDENT_ID_REGEX = os.environ.get("STUDENT_ID_REGEX", r"^SV-\d{8,12}$")
_student_id_pattern = re.compile(STUDENT_ID_REGEX, re.IGNORECASE)
JOIN_REQUEST_RATE_WINDOW_SECONDS = 60
JOIN_REQUEST_IP_LIMIT = 10
JOIN_REQUEST_STUDENT_LIMIT = 3
_join_request_attempts: Dict[str, List[float]] = {}
_join_request_rate_lock = threading.Lock()


def validate_student_id(student_id: str) -> str:
    clean = (student_id or "").strip().upper()
    if not _student_id_pattern.fullmatch(clean):
        raise HTTPException(
            status_code=400,
            detail=f"Mã sinh viên '{clean}' không hợp lệ theo quy định nhà trường.",
        )
    return clean


def _check_join_request_rate_limit(client_ip: str, student_id: str) -> None:
    now = time.monotonic()
    window_start = now - JOIN_REQUEST_RATE_WINDOW_SECONDS
    keys = (f"ip:{client_ip}", f"student:{student_id}")
    with _join_request_rate_lock:
        recent = {
            key: [timestamp for timestamp in _join_request_attempts.get(key, []) if timestamp > window_start]
            for key in keys
        }
        if len(recent[keys[0]]) >= JOIN_REQUEST_IP_LIMIT or len(recent[keys[1]]) >= JOIN_REQUEST_STUDENT_LIMIT:
            _join_request_attempts.update(recent)
            raise HTTPException(status_code=429, detail="Đã gửi quá nhiều yêu cầu vào thi. Vui lòng thử lại sau.")
        for key in keys:
            recent[key].append(now)
            _join_request_attempts[key] = recent[key]


def _get_teacher_exam(
    db: Session, exam_id: int, teacher: Teacher, include_questions: bool = False
) -> Optional[Exam]:
    query = db.query(Exam)
    if include_questions:
        query = query.options(selectinload(Exam.questions))
    if teacher.teacher_code != "GV-ADMIN":
        query = query.filter(Exam.teacher_id == teacher.id)
    return query.filter(Exam.id == exam_id).first()


# ══════════════════════════════════════════════════════════
# PYDANTIC SCHEMAS
# ══════════════════════════════════════════════════════════

class PublishRequest(BaseModel):
    """Body cho POST /api/exams/{id}/publish — cấu hình đề thi trước khi mở cho sinh viên."""
    duration_minutes: int = Field(..., ge=1, le=600, description="Thời gian làm bài (phút)")
    pass_score: float = Field(default=5.0, ge=0, le=10, description="Điểm đạt, thang 10")
    shuffle_questions: bool = Field(default=False, description="Trộn thứ tự câu hỏi cho từng SV")
    start_time: str = Field(..., min_length=1, description="Thời điểm mở đề theo giờ Việt Nam, ISO 8601")
    end_time: str = Field(..., min_length=1, description="Thời điểm đóng đề theo giờ Việt Nam, ISO 8601")


class AnswerItem(BaseModel):
    question_id: int
    selected_option: Optional[str] = Field(default=None, description="'A'/'B'/'C'/'D', hoặc null nếu bỏ trống")


class SubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: list[AnswerItem] = Field(default_factory=list)
    auto_submitted: bool = Field(
        default=False,
        description="True nếu do hệ thống tự động nộp khi hết giờ (client gửi lên), False nếu SV chủ động bấm Nộp bài",
    )


class JoinRequestCreate(BaseModel):
    """Body cho sinh viên xin vào thi POST /api/exams/{exam_id}/join-request."""
    model_config = ConfigDict(extra="forbid")

    student_id: str = Field(..., min_length=1, max_length=50)
    student_name: str = Field(..., min_length=1, max_length=150)
    device_info: Optional[str] = Field(default=None, max_length=255)


class RejectEnrollmentRequest(BaseModel):
    """Body cho Giảng viên từ chối sinh viên."""
    reason: Optional[str] = Field(default="Giảng viên từ chối cho phép vào phòng thi.", max_length=255)



def _parse_iso_datetime(value: str, field_name: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Định dạng thời gian '{field_name}' không hợp lệ (cần ISO 8601)") from exc


def _as_utc_naive(value: datetime) -> datetime:
    """Chuẩn hóa datetime SQLite (UTC naive) và datetime có múi giờ về UTC naive."""
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _check_available_exams_rate_limit(client_ip: str) -> None:
    now = time.monotonic()
    window_start = now - AVAILABLE_EXAMS_RATE_WINDOW_SECONDS
    with _available_exams_rate_lock:
        recent_requests = [
            timestamp
            for timestamp in _available_exams_requests.get(client_ip, [])
            if timestamp > window_start
        ]
        if len(recent_requests) >= AVAILABLE_EXAMS_RATE_LIMIT:
            _available_exams_requests[client_ip] = recent_requests
            raise HTTPException(
                status_code=429,
                detail="Đã vượt quá 60 yêu cầu danh sách đề thi mỗi phút. Vui lòng thử lại sau.",
            )
        recent_requests.append(now)
        _available_exams_requests[client_ip] = recent_requests


def _generate_exam_code(title: str) -> str:
    """Sinh mã đề thi ngắn gọn, dễ đọc, dùng khi giáo viên không tự đặt mã."""
    slug = _slugify_ascii(title)[:10] or "DETHI"
    return f"{slug}-{secrets.token_hex(2).upper()}"


def _slugify_ascii(text: str) -> str:
    """
    Chuẩn hoá 1 chuỗi bất kỳ (có thể chứa tiếng Việt có dấu) thành mã ASCII an toàn:
    bỏ dấu (NFD decompose rồi loại combining marks), chỉ giữ chữ/số, viết hoa.

    Áp dụng cho MỌI mã đề thi (dù giáo viên tự đặt hay hệ thống tự sinh) — lý do:
    mã đề thi có dấu tiếng Việt vừa khó gõ/đọc miệng cho sinh viên, vừa từng gây lỗi
    500 thật khi dùng để đặt tên file .xlsx xuất ra (HTTP header không encode được
    ký tự Unicode ngoài latin-1 trong Content-Disposition dạng ASCII thuần).
    """
    # "Đ"/"đ" là 1 code point Unicode ĐỘC LẬP (U+0110/U+0111, chữ D có gạch ngang),
    # KHÔNG phân rã được qua NFD normalization như các nguyên âm có dấu khác — phải
    # thay thế thủ công trước, nếu không mã đề sẽ sót lại ký tự "Đ" không phải ASCII.
    text = (text or "").replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFD", text)
    no_marks = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return "".join(ch for ch in no_marks.upper() if ch.isalnum() or ch in "-_")


# ══════════════════════════════════════════════════════════
# PHẦN A — QUẢN LÝ ĐỀ THI (GIẢNG VIÊN)
# ══════════════════════════════════════════════════════════

@router.post("/upload")
async def upload_exam(
    file: UploadFile = File(..., description="File đề thi .xlsx hoặc .docx theo đúng mẫu"),
    title: str = Form(..., min_length=1, max_length=255, description="Tên đề thi / học phần"),
    subject: str = Form(..., min_length=1, max_length=100, description="Tên môn học"),
    exam_code: Optional[str] = Form(default=None, description="Mã đề thi, bỏ trống để hệ thống tự sinh"),
    join_open_minutes: int = Form(default=15, ge=0, le=120, description="Cho phép SV xin vào trước giờ thi (phút)"),
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """
    [Cần token Giảng viên] Upload file đề thi, đọc & kiểm tra hợp lệ,
    tạo đề thi mới ở trạng thái DRAFT gắn với tài khoản Giảng viên và Môn học.
    """
    filename = file.filename or ""
    if not filename.lower().endswith(ALLOWED_UPLOAD_EXTENSIONS):
        raise HTTPException(
            status_code=400,
            detail=f"Chỉ chấp nhận file {' hoặc '.join(ALLOWED_UPLOAD_EXTENSIONS)}",
        )

    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File vượt quá dung lượng cho phép ({MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB)",
        )
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="File rỗng, không có dữ liệu")

    result = parse_exam_file(filename, file_bytes)

    if result.valid_count == 0:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Không đọc được câu hỏi hợp lệ nào từ file, đề thi KHÔNG được tạo.",
                "errors": [{"code": e.code, "location": e.location, "message": e.message} for e in result.errors],
            },
        )

    manual_code = _slugify_ascii(exam_code or "")
    code = manual_code or _generate_exam_code(title)
    normalized_subject = " ".join(subject.split())
    if not normalized_subject:
        raise HTTPException(status_code=422, detail="Vui lòng nhập môn học.")

    exam = Exam(
        exam_code=code,
        title=title.strip(),
        subject=normalized_subject,
        teacher_id=current_teacher.id,
        join_open_minutes=join_open_minutes,
        status=EXAM_STATUS_DRAFT,
        created_by=current_teacher.full_name,
    )
    weight = round(10.0 / result.valid_count, 4)
    exam.questions = [
        Question(
            order_index=q.order_index,
            content=q.content,
            option_a=q.option_a,
            option_b=q.option_b,
            option_c=q.option_c,
            option_d=q.option_d,
            correct_option=q.correct_option,
            score_weight=weight,
        )
        for q in result.questions
    ]

    try:
        db.add(exam)
        db.commit()
        db.refresh(exam)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Mã đề thi '{code}' đã tồn tại, vui lòng chọn mã khác")
    except Exception as exc:
        db.rollback()
        logger.error("Lỗi khi tạo đề thi: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi nội bộ máy chủ") from exc

    logger.info(
        "Giảng viên '%s' đã tạo đề thi DRAFT '%s' (môn: %s, id=%d) với %d câu hợp lệ",
        current_teacher.teacher_code, exam.exam_code, exam.subject, exam.id, result.valid_count,
    )

    return {
        "exam": exam.to_dict(include_questions=True, with_answers=True),
        "parse_errors": [
            {"code": e.code, "location": e.location, "message": e.message} for e in result.errors
        ],
    }


@router.get("")
def list_exams(
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """
    [Cần token Giảng viên] Danh sách đề thi.
    Giảng viên chỉ thấy đề thi do chính mình tạo; tài khoản admin dự phòng thấy toàn bộ đề.
    """
    query = db.query(Exam).options(selectinload(Exam.questions), selectinload(Exam.teacher))
    if current_teacher.teacher_code != "GV-ADMIN":
        query = query.filter(Exam.teacher_id == current_teacher.id)
    exams = query.order_by(Exam.created_at.desc()).all()
    return [e.to_dict() for e in exams]


@router.get("/available")
def get_available_exams(request: Request, db: Session = Depends(get_db)):
    """
    Danh sách đề công khai trong đúng cửa sổ đăng ký, giới hạn 60 yêu cầu/IP/phút.
    Chỉ trả metadata đề thi; tuyệt đối không tải câu hỏi hay đáp án.
    """
    client_ip = request.client.host if request.client else "unknown"
    _check_available_exams_rate_limit(client_ip)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    exam_rows = (
        db.query(Exam)
        .options(selectinload(Exam.teacher))
        .filter(Exam.status == EXAM_STATUS_PUBLISHED)
        .order_by(Exam.subject.asc(), Exam.created_at.desc())
        .all()
    )
    exams = [
        exam
        for exam in exam_rows
        if exam.start_time
        and exam.end_time
        and _as_utc_naive(exam.start_time) - timedelta(
            minutes=exam.join_open_minutes if exam.join_open_minutes is not None else 15
        )
        <= now
        <= _as_utc_naive(exam.end_time)
    ]
    question_counts = dict(
        db.query(Question.exam_id, func.count(Question.id))
        .filter(Question.exam_id.in_([exam.id for exam in exams]))
        .group_by(Question.exam_id)
        .all()
    ) if exams else {}

    grouped: Dict[str, list] = {}
    for e in exams:
        start_utc = _as_utc_naive(e.start_time)
        end_utc = _as_utc_naive(e.end_time)

        teacher_name = e.teacher.full_name if e.teacher else (e.created_by or "Giảng viên")
        subject_name = e.subject or "Chưa phân môn"
        grouped.setdefault(subject_name, []).append({
            "exam_id": e.id,
            "exam_code": e.exam_code,
            "title": e.title,
            "teacher_name": teacher_name,
            "start_time": start_utc.isoformat(),
            "end_time": end_utc.isoformat(),
            "duration_minutes": e.duration_minutes,
            "total_questions": question_counts.get(e.id, 0),
        })

    return [
        {"subject": subject_name, "exams": exam_list}
        for subject_name, exam_list in grouped.items()
    ]


@router.get("/enrollments")
def list_teacher_enrollments(
    request: Request,
    subject: Optional[str] = Query(default=None),
    exam_id: Optional[int] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """[Giảng viên] Danh sách yêu cầu của đề thuộc quyền sở hữu, có thể lọc theo môn/đề/trạng thái."""
    valid_statuses = {
        ENROLLMENT_STATUS_PENDING,
        ENROLLMENT_STATUS_APPROVED,
        ENROLLMENT_STATUS_REJECTED,
        ENROLLMENT_STATUS_REVOKED,
    }
    if status_filter and status_filter.upper() not in valid_statuses:
        raise HTTPException(status_code=400, detail="Trạng thái ghi danh không hợp lệ.")
    query = db.query(ExamEnrollment).join(Exam, ExamEnrollment.exam_id == Exam.id)
    if current_teacher.teacher_code != "GV-ADMIN":
        query = query.filter(Exam.teacher_id == current_teacher.id)
    if subject:
        query = query.filter(Exam.subject == " ".join(subject.split()))
    if exam_id is not None:
        query = query.filter(Exam.id == exam_id)
    if status_filter:
        query = query.filter(ExamEnrollment.status == status_filter.upper())
    enrollments = query.order_by(ExamEnrollment.requested_at.desc()).all()
    return [_enrollment_with_history(item, db, request) for item in enrollments]


@router.get("/{exam_id}")
def get_exam_detail(
    exam_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """[Cần token Giảng viên] Chi tiết 1 đề thi, bao gồm đáp án đúng."""
    exam = _get_teacher_exam(db, exam_id, current_teacher, include_questions=True)
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi")
    return exam.to_dict(include_questions=True, with_answers=True)


@router.post("/{exam_id}/publish")
def publish_exam(
    exam_id: int,
    payload: PublishRequest,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """
    [Cần token Giảng viên] Công bố đề thi: chuyển DRAFT -> PUBLISHED kèm cấu hình thời gian làm bài.
    """
    exam = _get_teacher_exam(db, exam_id, current_teacher)
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi")
    if exam.status == EXAM_STATUS_CLOSED:
        raise HTTPException(status_code=400, detail="Đề thi đã đóng, không thể công bố lại")

    start_dt = _parse_iso_datetime(payload.start_time, "start_time")
    end_dt = _parse_iso_datetime(payload.end_time, "end_time")
    if end_dt <= start_dt:
        raise HTTPException(status_code=400, detail="Thời điểm đóng đề phải sau thời điểm mở đề")

    exam.duration_minutes = payload.duration_minutes
    exam.pass_score = payload.pass_score
    exam.shuffle_questions = payload.shuffle_questions
    exam.start_time = start_dt
    exam.end_time = end_dt
    exam.status = EXAM_STATUS_PUBLISHED

    db.commit()
    db.refresh(exam)
    logger.info("Giảng viên '%s' đã công bố đề thi '%s' (id=%d)", current_teacher.teacher_code, exam.exam_code, exam.id)
    return exam.to_dict()


@router.post("/{exam_id}/close")
def close_exam(
    exam_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """[Cần token Giảng viên] Đóng đề đã công bố; đề CLOSED bị ẩn khỏi danh sách thi."""
    exam = _get_teacher_exam(db, exam_id, current_teacher)
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi")
    if exam.status == EXAM_STATUS_DRAFT:
        raise HTTPException(status_code=400, detail="Chỉ có thể đóng đề thi đã công bố")
    exam.status = EXAM_STATUS_CLOSED
    db.commit()
    db.refresh(exam)
    logger.info("Giảng viên '%s' đã đóng đề thi '%s' (id=%d)", current_teacher.teacher_code, exam.exam_code, exam.id)
    return exam.to_dict()


@router.delete("/{exam_id}")
def delete_exam(
    exam_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """[Cần token Giảng viên] Xóa đề thi — CHỈ cho phép khi chưa có sinh viên nào nộp bài."""
    exam = _get_teacher_exam(db, exam_id, current_teacher)
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi")

    submission_count = db.query(ExamSubmission).filter(ExamSubmission.exam_id == exam_id).count()
    if submission_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Đề thi đã có {submission_count} sinh viên nộp bài, không thể xóa để tránh mất dữ liệu điểm",
        )

    db.delete(exam)
    db.commit()
    logger.info("Giảng viên '%s' đã xóa đề thi '%s' (id=%d)", current_teacher.teacher_code, exam.exam_code, exam_id)
    return {"message": "Đã xóa đề thi thành công"}


# ══════════════════════════════════════════════════════════
# PHẦN ĐĂNG KÝ VÀ DUYỆT THÍ SINH (ENROLLMENT WORKFLOW)
# ══════════════════════════════════════════════════════════

def _within_join_window(exam: Exam, now: datetime) -> bool:
    if exam.status != EXAM_STATUS_PUBLISHED or not exam.start_time or not exam.end_time:
        return False
    start_time = _as_utc_naive(exam.start_time)
    end_time = _as_utc_naive(exam.end_time)
    join_open_minutes = exam.join_open_minutes if exam.join_open_minutes is not None else 15
    return start_time - timedelta(minutes=join_open_minutes) <= now <= end_time


def _enrollment_with_history(enrollment: ExamEnrollment, db: Session, request: Request) -> dict:
    violations = db.query(Violation).filter(
        Violation.student_id == enrollment.student_id
    )
    total = violations.count()
    by_type = dict(
        db.query(Violation.violation_type, func.count(Violation.id))
        .filter(Violation.student_id == enrollment.student_id)
        .group_by(Violation.violation_type)
        .all()
    )
    latest_at = (
        db.query(func.max(Violation.captured_at))
        .filter(Violation.student_id == enrollment.student_id)
        .scalar()
    )
    recent_images = (
        violations.filter(Violation.image_path.isnot(None))
        .order_by(Violation.captured_at.desc(), Violation.id.desc())
        .limit(5)
        .all()
    )
    base_url = str(request.base_url).rstrip("/")
    result = enrollment.to_dict()
    result["violation_summary"] = {
        "total": total,
        "by_type": by_type,
        "latest_at": _naive_utc_iso(latest_at) if latest_at else None,
        "recent_images": [
            {
                "id": violation.id,
                "violation_type": violation.violation_type,
                "captured_at": _naive_utc_iso(_as_utc_naive(violation.captured_at)),
                "image_url": violation.to_dict(base_url).get("image_url"),
            }
            for violation in recent_images
        ],
    }
    return result


@router.get("/join-request/status")
def get_join_request_status(
    x_request_token: Optional[str] = Header(default=None, alias="X-Request-Token"),
    db: Session = Depends(get_db),
):
    """Kiểm tra yêu cầu; trả exam_session_token đúng một lần sau khi được duyệt."""
    if not x_request_token:
        raise HTTPException(status_code=401, detail="Thiếu mã yêu cầu vào thi (X-Request-Token).")
    enrollment = (
        db.query(ExamEnrollment)
        .filter(ExamEnrollment.request_token_hash == hash_token(x_request_token.strip()))
        .first()
    )
    if not enrollment:
        raise HTTPException(status_code=401, detail="Yêu cầu vào thi không tồn tại hoặc không hợp lệ.")

    response = {
        "id": enrollment.id,
        "exam_id": enrollment.exam_id,
        "student_id": enrollment.student_id,
        "student_name": enrollment.student_name,
        "status": enrollment.status,
        "reject_reason": enrollment.reject_reason,
    }
    if enrollment.status == ENROLLMENT_STATUS_APPROVED and not enrollment.session_token_issued:
        raw_session_token = secrets.token_urlsafe(32)
        claimed = (
            db.query(ExamEnrollment)
            .filter(
                ExamEnrollment.id == enrollment.id,
                ExamEnrollment.status == ENROLLMENT_STATUS_APPROVED,
                ExamEnrollment.session_token_issued.is_(False),
            )
            .update(
                {
                    ExamEnrollment.session_token_hash: hash_token(raw_session_token),
                    ExamEnrollment.session_token_issued: True,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        if claimed:
            response["exam_session_token"] = raw_session_token
            response["exam_code"] = enrollment.exam.exam_code
            response["exam_title"] = enrollment.exam.title
    return response


@router.post("/join-request/cancel")
def cancel_join_request(
    x_request_token: Optional[str] = Header(default=None, alias="X-Request-Token"),
    db: Session = Depends(get_db),
):
    """Hủy một yêu cầu đang chờ; trạng thái REVOKED được dùng vì không có trạng thái CANCELLED."""
    if not x_request_token:
        raise HTTPException(status_code=401, detail="Thiếu mã yêu cầu vào thi (X-Request-Token).")
    enrollment = (
        db.query(ExamEnrollment)
        .filter(ExamEnrollment.request_token_hash == hash_token(x_request_token.strip()))
        .first()
    )
    if not enrollment:
        raise HTTPException(status_code=401, detail="Yêu cầu vào thi không tồn tại hoặc không hợp lệ.")
    if enrollment.status != ENROLLMENT_STATUS_PENDING:
        raise HTTPException(status_code=409, detail="Chỉ có thể hủy yêu cầu đang chờ duyệt.")
    enrollment.status = ENROLLMENT_STATUS_REVOKED
    enrollment.request_token_hash = None
    enrollment.session_token_hash = None
    enrollment.session_token_issued = False
    db.commit()
    return {"success": True, "status": enrollment.status}


@router.post("/{exam_id}/join-request")
def create_join_request(
    exam_id: int,
    payload: JoinRequestCreate,
    request: Request,
    x_request_token: Optional[str] = Header(default=None, alias="X-Request-Token"),
    db: Session = Depends(get_db),
):
    """
    [Sinh viên] Gửi yêu cầu xin vào phòng thi.
    Kiểm tra mã SV hợp lệ, đề thi đang mở, chưa quá hạn nộp.
    Mã SV trong yêu cầu chỉ là thông tin khai báo; phiên thi chỉ hợp lệ sau khi được duyệt.
    """
    student_id = validate_student_id(payload.student_id)
    student_name = payload.student_name.strip()
    if not student_name:
        raise HTTPException(status_code=400, detail="Vui lòng nhập họ và tên sinh viên")

    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi")
    if exam.status != EXAM_STATUS_PUBLISHED:
        raise HTTPException(status_code=403, detail="Đề thi chưa được công bố hoặc đã đóng")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if not _within_join_window(exam, now):
        raise HTTPException(status_code=403, detail="Đề thi hiện không nằm trong cửa sổ xin vào thi.")

    # Kiểm tra sinh viên đã nộp bài trước đó chưa
    already_submitted = (
        db.query(ExamSubmission.id)
        .filter(ExamSubmission.exam_id == exam.id, ExamSubmission.student_id == student_id)
        .first()
    )
    if already_submitted:
        raise HTTPException(status_code=409, detail="Bạn đã hoàn thành và nộp bài cho đề thi này rồi")

    client_ip = request.client.host if request.client else "unknown"
    _check_join_request_rate_limit(client_ip, student_id)

    enrollment = (
        db.query(ExamEnrollment)
        .filter(ExamEnrollment.exam_id == exam.id, ExamEnrollment.student_id == student_id)
        .first()
    )
    supplied_request_token = (x_request_token or "").strip()
    if (
        enrollment
        and supplied_request_token
        and enrollment.request_token_hash
        and secrets.compare_digest(
            hash_token(supplied_request_token), enrollment.request_token_hash
        )
    ):
        return {
            "enrollment_id": enrollment.id,
            "status": enrollment.status,
            "student_id": enrollment.student_id,
            "student_name": enrollment.student_name,
            "exam_id": exam.id,
            "exam_code": exam.exam_code,
            "exam_title": exam.title,
        }

    # Một yêu cầu mới vô hiệu hóa token và mọi yêu cầu/phiên cũ của mã SV.
    db.query(ExamEnrollment).filter(
        ExamEnrollment.student_id == student_id,
    ).update(
        {ExamEnrollment.request_token_hash: None},
        synchronize_session=False,
    )
    db.query(ExamEnrollment).filter(
        ExamEnrollment.student_id == student_id,
        ExamEnrollment.status.in_(
            (ENROLLMENT_STATUS_PENDING, ENROLLMENT_STATUS_APPROVED)
        ),
    ).update(
        {
            ExamEnrollment.status: ENROLLMENT_STATUS_REVOKED,
            ExamEnrollment.session_token_issued: False,
        },
        synchronize_session=False,
    )

    raw_request_token = secrets.token_urlsafe(32)
    if enrollment:
        enrollment.status = ENROLLMENT_STATUS_PENDING
        enrollment.reject_reason = None
        enrollment.requested_at = now
        enrollment.decided_at = None
        enrollment.decided_by = None
        enrollment.student_name = student_name
        enrollment.device_info = payload.device_info
        enrollment.ip = client_ip
        enrollment.request_token_hash = hash_token(raw_request_token)
        enrollment.session_token_hash = None
        enrollment.session_token_issued = False
    else:
        enrollment = ExamEnrollment(
            exam_id=exam.id,
            student_id=student_id,
            student_name=student_name,
            status=ENROLLMENT_STATUS_PENDING,
            request_token_hash=hash_token(raw_request_token),
            requested_at=now,
            device_info=payload.device_info,
            ip=client_ip,
        )
        db.add(enrollment)

    db.commit()
    db.refresh(enrollment)

    return {
        "enrollment_id": enrollment.id,
        "status": enrollment.status,
        "student_id": enrollment.student_id,
        "student_name": enrollment.student_name,
        "exam_id": exam.id,
        "exam_code": exam.exam_code,
        "exam_title": exam.title,
        "request_token": raw_request_token,
    }


@router.get("/{exam_id}/enrollments")
def list_exam_enrollments(
    exam_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """[Cần token Giảng viên] Danh sách sinh viên đăng ký thi của 1 đề thi."""
    exam = _get_teacher_exam(db, exam_id, current_teacher)
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi")

    enrollments = (
        db.query(ExamEnrollment)
        .filter(ExamEnrollment.exam_id == exam_id)
        .order_by(ExamEnrollment.requested_at.desc())
        .all()
    )
    return [_enrollment_with_history(item, db, request) for item in enrollments]


@router.post("/{exam_id}/enrollments/approve-all")
def approve_all_enrollments(
    exam_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """[Cần token Giảng viên] Duyệt toàn bộ yêu cầu PENDING của đề thuộc quyền sở hữu."""
    exam = _get_teacher_exam(db, exam_id, current_teacher)
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi")
    pending = db.query(ExamEnrollment).filter(
        ExamEnrollment.exam_id == exam.id,
        ExamEnrollment.status == ENROLLMENT_STATUS_PENDING,
        ExamEnrollment.request_token_hash.isnot(None),
    ).all()
    now = datetime.now(timezone.utc)
    for enrollment in pending:
        db.query(ExamEnrollment).filter(
            ExamEnrollment.student_id == enrollment.student_id,
            ExamEnrollment.status == ENROLLMENT_STATUS_APPROVED,
            ExamEnrollment.id != enrollment.id,
        ).update(
            {
                ExamEnrollment.status: ENROLLMENT_STATUS_REVOKED,
                ExamEnrollment.session_token_issued: False,
            },
            synchronize_session=False,
        )
        enrollment.status = ENROLLMENT_STATUS_APPROVED
        enrollment.decided_at = now
        enrollment.decided_by = current_teacher.id
        enrollment.reject_reason = None
    db.commit()
    return {"success": True, "approved_count": len(pending)}


@router.post("/{exam_id}/enrollments/{enrollment_id}/approve")
def approve_enrollment(
    exam_id: int,
    enrollment_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """[Cần token Giảng viên] Duyệt yêu cầu và kích hoạt phiên thi đã băm."""
    exam = _get_teacher_exam(db, exam_id, current_teacher)
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi")
    enrollment = (
        db.query(ExamEnrollment)
        .filter(ExamEnrollment.id == enrollment_id, ExamEnrollment.exam_id == exam.id)
        .first()
    )
    if not enrollment:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu đăng ký")

    if enrollment.status != ENROLLMENT_STATUS_PENDING or not enrollment.request_token_hash:
        raise HTTPException(
            status_code=409,
            detail="Sinh viên cần gửi lại yêu cầu vào thi trước khi được duyệt.",
        )
    db.query(ExamEnrollment).filter(
        ExamEnrollment.student_id == enrollment.student_id,
        ExamEnrollment.status == ENROLLMENT_STATUS_APPROVED,
        ExamEnrollment.id != enrollment.id,
    ).update(
        {
            ExamEnrollment.status: ENROLLMENT_STATUS_REVOKED,
            ExamEnrollment.session_token_issued: False,
        },
        synchronize_session=False,
    )
    enrollment.status = ENROLLMENT_STATUS_APPROVED
    enrollment.decided_at = datetime.now(timezone.utc)
    enrollment.decided_by = current_teacher.id
    enrollment.reject_reason = None
    enrollment.session_token_issued = False
    db.commit()
    db.refresh(enrollment)
    logger.info("Giảng viên '%s' đã DUYỆT sinh viên '%s' vào đề thi %d", current_teacher.teacher_code, enrollment.student_id, exam_id)
    return {"success": True, "enrollment": enrollment.to_dict()}


@router.post("/{exam_id}/enrollments/{enrollment_id}/reject")
def reject_enrollment(
    exam_id: int,
    enrollment_id: int,
    payload: RejectEnrollmentRequest,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """[Cần token Giảng viên] Từ chối không cho sinh viên vào thi."""
    exam = _get_teacher_exam(db, exam_id, current_teacher)
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi")
    enrollment = (
        db.query(ExamEnrollment)
        .filter(ExamEnrollment.id == enrollment_id, ExamEnrollment.exam_id == exam.id)
        .first()
    )
    if not enrollment:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu đăng ký")

    enrollment.status = ENROLLMENT_STATUS_REJECTED
    enrollment.decided_at = datetime.now(timezone.utc)
    enrollment.decided_by = current_teacher.id
    enrollment.reject_reason = payload.reason or "Giảng viên từ chối cho phép vào phòng thi."
    enrollment.session_token_issued = False
    db.commit()
    db.refresh(enrollment)
    logger.info("Giảng viên '%s' đã TỪ CHỐI sinh viên '%s' vào đề thi %d", current_teacher.teacher_code, enrollment.student_id, exam_id)
    return {"success": True, "enrollment": enrollment.to_dict()}


@router.post("/{exam_id}/enrollments/{enrollment_id}/revoke")
def revoke_enrollment(
    exam_id: int,
    enrollment_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """[Cần token Giảng viên] Thu hồi quyền thi (đình chỉ thi) của sinh viên."""
    exam = _get_teacher_exam(db, exam_id, current_teacher)
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi")
    enrollment = (
        db.query(ExamEnrollment)
        .filter(ExamEnrollment.id == enrollment_id, ExamEnrollment.exam_id == exam.id)
        .first()
    )
    if not enrollment:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu đăng ký")

    enrollment.status = ENROLLMENT_STATUS_REVOKED
    enrollment.decided_at = datetime.now(timezone.utc)
    enrollment.decided_by = current_teacher.id
    enrollment.session_token_issued = False
    db.commit()
    db.refresh(enrollment)
    logger.info("Giảng viên '%s' đã THU HỒI quyền thi của sinh viên '%s' ở đề thi %d", current_teacher.teacher_code, enrollment.student_id, exam_id)
    return {"success": True, "enrollment": enrollment.to_dict()}



# ══════════════════════════════════════════════════════════
# PHẦN B — SINH VIÊN LÀM BÀI & NỘP BÀI
# ══════════════════════════════════════════════════════════

@router.get("/code/{exam_code}/take")
def take_exam(
    exam_code: str,
    enrollment: ExamEnrollment = Depends(get_exam_session),
    db: Session = Depends(get_db),
):
    """
    Lấy đề thi để sinh viên làm bài, theo đúng mã đề — TUYỆT ĐỐI KHÔNG trả đáp án đúng.
    Nếu client gửi X-Exam-Session, kiểm tra phiên thi đã được Giảng viên phê duyệt.
    """
    exam = (
        db.query(Exam)
        .options(selectinload(Exam.questions))
        .filter(Exam.exam_code == exam_code.strip().upper())
        .first()
    )
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi với mã này")
    if exam.status != EXAM_STATUS_PUBLISHED:
        raise HTTPException(status_code=403, detail="Đề thi chưa được công bố hoặc đã đóng")

    if enrollment.exam_id != exam.id:
        raise HTTPException(status_code=403, detail="Phiên thi không khớp với đề thi này")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if exam.start_time and now < exam.start_time:
        raise HTTPException(status_code=403, detail="Chưa đến thời gian mở đề thi")
    if exam.end_time and now > exam.end_time:
        raise HTTPException(status_code=403, detail="Đề thi đã hết thời gian làm bài")

    questions = list(exam.questions)
    if exam.shuffle_questions:
        import random
        random.shuffle(questions)

    return {
        "exam_id": exam.id,
        "exam_code": exam.exam_code,
        "title": exam.title,
        "subject": exam.subject,
        "duration_minutes": exam.duration_minutes,
        "questions": [q.to_dict(with_answer=False) for q in questions],
    }


def _naive_utc_iso(dt: datetime) -> str:
    """Trả chuỗi ISO 8601 có hậu tố Z cho 1 datetime UTC không kèm múi giờ."""
    return dt.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


@router.post("/code/{exam_code}/start")
def start_exam(
    exam_code: str,
    enrollment: ExamEnrollment = Depends(get_exam_session),
    db: Session = Depends(get_db),
):
    """
    Ghi nhận thời điểm sinh viên BẮT ĐẦU làm bài (lần đầu tiên) và trả về thời gian CÒN LẠI
    tính theo đồng hồ của server. Idempotent: gọi lại không cấp lại thời gian từ đầu mà trả về phần còn lại.
    """
    exam = db.query(Exam).filter(Exam.exam_code == exam_code.strip().upper()).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi với mã này")
    if exam.status != EXAM_STATUS_PUBLISHED:
        raise HTTPException(status_code=403, detail="Đề thi chưa được công bố hoặc đã đóng")

    if enrollment.exam_id != exam.id:
        raise HTTPException(status_code=403, detail="Phiên thi không khớp với đề thi này")
    student_id = enrollment.student_id

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if exam.start_time and now < exam.start_time:
        raise HTTPException(status_code=403, detail="Chưa đến thời gian mở đề thi")
    if exam.end_time and now > exam.end_time:
        raise HTTPException(status_code=403, detail="Đề thi đã hết thời gian làm bài")

    already_submitted = (
        db.query(ExamSubmission.id)
        .filter(ExamSubmission.exam_id == exam.id, ExamSubmission.student_id == student_id)
        .first()
    )
    if already_submitted:
        raise HTTPException(status_code=409, detail="Sinh viên này đã nộp bài cho đề thi rồi")

    start = (
        db.query(ExamStart)
        .filter(ExamStart.exam_id == exam.id, ExamStart.student_id == student_id)
        .first()
    )
    if not start:
        start = ExamStart(exam_id=exam.id, student_id=student_id, started_at=now)
        try:
            db.add(start)
            db.commit()
            db.refresh(start)
        except IntegrityError:
            db.rollback()
            start = (
                db.query(ExamStart)
                .filter(ExamStart.exam_id == exam.id, ExamStart.student_id == student_id)
                .first()
            )
            if not start:
                raise HTTPException(status_code=500, detail="Lỗi nội bộ máy chủ")

    duration_seconds = max(1, exam.duration_minutes or 0) * 60
    elapsed = max(0.0, (now - start.started_at).total_seconds())
    remaining = max(0, int(duration_seconds - elapsed))

    return {
        "started_at": _naive_utc_iso(start.started_at),
        "server_time": _naive_utc_iso(now),
        "duration_seconds": duration_seconds,
        "remaining_seconds": remaining,
    }


@router.post("/code/{exam_code}/submit")
def submit_exam(
    exam_code: str,
    payload: SubmitRequest,
    enrollment: ExamEnrollment = Depends(get_exam_session),
    db: Session = Depends(get_db),
):
    """
    Sinh viên nộp bài làm — hệ thống CHẤM ĐIỂM TỰ ĐỘNG ngay lập tức trong cùng request này.
    Chỉ nhận phiên thi đã duyệt; nếu chưa có bản ghi bắt đầu hoặc yêu cầu đến sau
    min(started_at + duration_minutes + 15 giây, end_time), trả 403 và không chấm/lưu bài.
    Khoảng 15 giây là ân hạn cố định cho độ trễ gửi bài; không cộng dồn vào end_time.
    """
    exam = (
        db.query(Exam)
        .options(selectinload(Exam.questions))
        .filter(Exam.exam_code == exam_code.strip().upper())
        .first()
    )
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi với mã này")
    if exam.status != EXAM_STATUS_PUBLISHED:
        raise HTTPException(status_code=403, detail="Đề thi chưa được công bố hoặc đã đóng, không thể nộp bài")

    if enrollment.exam_id != exam.id:
        raise HTTPException(status_code=403, detail="Phiên thi không khớp với đề thi này")
    student_id = enrollment.student_id

    # 2. Chặn nộp trùng
    existing = (
        db.query(ExamSubmission)
        .filter(ExamSubmission.exam_id == exam.id, ExamSubmission.student_id == student_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Sinh viên này đã nộp bài cho đề thi rồi, không thể nộp lại")

    # 3. Từ chối bài nộp trễ hạn trước khi chấm điểm hoặc ghi dữ liệu.
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    submission_grace = timedelta(seconds=15)
    start_record = (
        db.query(ExamStart)
        .filter(ExamStart.exam_id == exam.id, ExamStart.student_id == student_id)
        .first()
    )
    if not start_record or not exam.duration_minutes:
        raise HTTPException(
            status_code=403,
            detail="Không tìm thấy thời điểm bắt đầu bài thi hợp lệ. Bài nộp bị từ chối và không được chấm điểm.",
        )

    deadline = _as_utc_naive(start_record.started_at) + timedelta(
        minutes=exam.duration_minutes
    )
    deadline += submission_grace
    if exam.end_time:
        deadline = min(deadline, _as_utc_naive(exam.end_time))
    if now_utc > deadline:
        raise HTTPException(
            status_code=403,
            detail="Đã quá hạn nộp bài (hạn là thời điểm sớm hơn giữa thời gian làm bài cộng 15 giây và giờ kết thúc đề). Bài nộp bị từ chối và không được chấm điểm.",
        )

    # ── CHẤM ĐIỂM TỰ ĐỘNG ──
    questions_by_id = {q.id: q for q in exam.questions}
    answer_map = {a.question_id: (a.selected_option or "").strip().upper() or None for a in payload.answers}

    total_score = 0.0
    correct_count = 0
    submission_answers: list[SubmissionAnswer] = []

    for q in exam.questions:
        selected = answer_map.get(q.id)
        is_correct = selected is not None and selected == q.correct_option
        if is_correct:
            correct_count += 1
            total_score += q.score_weight
        submission_answers.append(
            SubmissionAnswer(question_id=q.id, selected_option=selected, is_correct=is_correct)
        )

    submission = ExamSubmission(
        exam_id=exam.id,
        student_id=student_id,
        student_name=enrollment.student_name,
        started_at=start_record.started_at if start_record else None,
        submitted_at=now_utc,
        total_score=round(min(total_score, 10.0), 2),
        correct_count=correct_count,
        total_questions=len(exam.questions),
        status=SUBMISSION_STATUS_AUTO_SUBMITTED if payload.auto_submitted else SUBMISSION_STATUS_SUBMITTED,
        answers=submission_answers,
    )

    try:
        db.add(submission)
        db.commit()
        db.refresh(submission)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Sinh viên này đã nộp bài cho đề thi rồi, không thể nộp lại")
    except Exception as exc:
        db.rollback()
        logger.error("Lỗi khi chấm điểm/lưu bài nộp: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Lỗi nội bộ máy chủ") from exc

    logger.info(
        "SV '%s' đã nộp bài đề '%s': %.2f điểm (%d/%d câu đúng)",
        student_id, exam.exam_code, submission.total_score, correct_count, len(exam.questions),
    )

    return {
        "total_score": submission.total_score,
        "correct_count": correct_count,
        "total_questions": len(exam.questions),
        "pass_score": exam.pass_score,
        "passed": submission.total_score >= exam.pass_score,
        "status": submission.status,
    }


# ══════════════════════════════════════════════════════════
# PHẦN C — KẾT QUẢ & XUẤT BÁO CÁO (GIẢNG VIÊN)
# ══════════════════════════════════════════════════════════

def _build_results_rows(exam: Exam, db: Session) -> list[dict]:
    """Dựng danh sách bảng điểm cho 1 đề thi kèm số lần vi phạm."""
    submissions = (
        db.query(ExamSubmission)
        .filter(ExamSubmission.exam_id == exam.id)
        .order_by(ExamSubmission.total_score.desc().nullslast())
        .all()
    )

    rows = []
    for s in submissions:
        violation_query = db.query(Violation).filter(
            Violation.student_id == s.student_id,
            Violation.exam_id == exam.id,
        )
        violation_count = violation_query.count()

        rows.append(
            {
                "student_id": s.student_id,
                "student_name": s.student_name,
                "total_score": s.total_score,
                "correct_count": s.correct_count,
                "total_questions": s.total_questions,
                "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
                "status": s.status,
                "violation_count": violation_count,
                "passed": (s.total_score or 0) >= exam.pass_score,
            }
        )
    return rows


@router.get("/{exam_id}/results")
def get_exam_results(
    exam_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """[Cần token Giảng viên] Bảng điểm toàn bộ sinh viên đã nộp bài của 1 đề, kèm số lần vi phạm."""
    exam = _get_teacher_exam(db, exam_id, current_teacher)
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi")

    return {
        "exam": exam.to_dict(),
        "results": _build_results_rows(exam, db),
    }


@router.get("/{exam_id}/export")
def export_exam_results(
    exam_id: int,
    db: Session = Depends(get_db),
    current_teacher: Teacher = Depends(get_current_teacher),
):
    """[Cần token Giảng viên] Xuất file .xlsx bảng điểm của 1 đề thi."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    exam = _get_teacher_exam(db, exam_id, current_teacher)
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi")

    rows = _build_results_rows(exam, db)
    if not rows:
        raise HTTPException(status_code=400, detail="Đề thi chưa có sinh viên nào nộp bài, không có dữ liệu để xuất")

    wb = Workbook()
    ws = wb.active
    ws.title = "Bảng điểm"

    headers = ["Mã SV", "Họ và tên", "Điểm số", "Số câu đúng", "Tổng số câu", "Số lần vi phạm", "Trạng thái"]
    ws.append(headers)

    header_fill = PatternFill(start_color="1F3864", end_color="1F3864", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for r in rows:
        ws.append(
            [
                r["student_id"],
                r["student_name"] or "",
                r["total_score"],
                r["correct_count"],
                r["total_questions"],
                r["violation_count"],
                "Đạt" if r["passed"] else "Không đạt",
            ]
        )

    for col_idx, header in enumerate(headers, start=1):
        max_len = max([len(str(header))] + [len(str(row[col_idx - 1])) for row in ws.iter_rows(min_row=2, values_only=True)])
        ws.column_dimensions[get_column_letter(col_idx)].width = max_len + 4

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"BangDiem_{exam.exam_code}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii") or "BangDiem.xlsx"
    from urllib.parse import quote
    content_disposition = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition},
    )
