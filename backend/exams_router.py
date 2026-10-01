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

  PHẦN B — Sinh viên làm bài (KHÔNG cần token, xác thực bằng đúng mã đề + trạng thái):
      GET    /api/exams/code/{exam_code}/take    Lấy đề để làm bài (KHÔNG kèm đáp án đúng)
      POST   /api/exams/code/{exam_code}/submit  Nộp bài — chấm điểm tự động ngay lập tức

  PHẦN C — Kết quả & Xuất báo cáo (dành cho Giảng viên, cần token):
      GET    /api/exams/{id}/results       Bảng điểm toàn bộ SV đã nộp, kèm số lần vi phạm
      GET    /api/exams/{id}/export        Xuất file .xlsx bảng điểm
"""

import io
import logging
import secrets
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from auth import verify_proctor_token
from database import (
    Exam,
    ExamStart,
    ExamSubmission,
    Question,
    SubmissionAnswer,
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

ALLOWED_UPLOAD_EXTENSIONS = (".xlsx", ".docx")
MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024  # 5MB — theo mục 4.3 đặc tả


# ══════════════════════════════════════════════════════════
# PYDANTIC SCHEMAS
# ══════════════════════════════════════════════════════════

class PublishRequest(BaseModel):
    """Body cho POST /api/exams/{id}/publish — cấu hình đề thi trước khi mở cho sinh viên."""
    duration_minutes: int = Field(..., ge=1, le=600, description="Thời gian làm bài (phút)")
    pass_score: float = Field(default=5.0, ge=0, le=10, description="Điểm đạt, thang 10")
    shuffle_questions: bool = Field(default=False, description="Trộn thứ tự câu hỏi cho từng SV")
    start_time: Optional[str] = Field(default=None, description="Thời điểm mở đề (ISO 8601), bỏ trống = mở ngay")
    end_time: Optional[str] = Field(default=None, description="Thời điểm đóng đề (ISO 8601), bỏ trống = không giới hạn")


class AnswerItem(BaseModel):
    question_id: int
    selected_option: Optional[str] = Field(default=None, description="'A'/'B'/'C'/'D', hoặc null nếu bỏ trống")


class StartRequest(BaseModel):
    """Body cho POST /api/exams/code/{exam_code}/start — sinh viên bấm "Bắt đầu làm bài"."""
    student_id: str = Field(..., min_length=1, max_length=50)


class SubmitRequest(BaseModel):
    student_id: str = Field(..., min_length=1, max_length=50)
    student_name: Optional[str] = Field(default=None, max_length=150)
    answers: list[AnswerItem] = Field(default_factory=list)
    auto_submitted: bool = Field(
        default=False,
        description="True nếu do hệ thống tự động nộp khi hết giờ (client gửi lên), False nếu SV chủ động bấm Nộp bài",
    )


def _parse_iso_datetime(value: Optional[str], field_name: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Định dạng thời gian '{field_name}' không hợp lệ (cần ISO 8601)") from exc


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
    exam_code: Optional[str] = Form(default=None, description="Mã đề thi, bỏ trống để hệ thống tự sinh"),
    created_by: Optional[str] = Form(default=None, max_length=50, description="Mã giảng viên tạo đề"),
    db: Session = Depends(get_db),
    _auth: None = Depends(verify_proctor_token),
):
    """
    [Cần token Giám thị] Upload file đề thi, đọc & kiểm tra hợp lệ (Chương 6 đặc tả),
    tạo đề thi mới ở trạng thái DRAFT với các câu hỏi hợp lệ đọc được.

    Trả về đề thi vừa tạo (kèm đáp án đúng để giáo viên xem trước) + danh sách lỗi phát hiện
    được (nếu có) — MỘT VÀI DÒNG LỖI KHÔNG làm hỏng toàn bộ việc đọc file (đúng nguyên tắc
    thiết kế tại mục 6.3 đặc tả).
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

    # Không tạo đề thi nếu KHÔNG có câu hỏi hợp lệ nào (ERR_EMPTY_FILE / ERR_TOO_MANY_QUESTIONS)
    if result.valid_count == 0:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Không đọc được câu hỏi hợp lệ nào từ file, đề thi KHÔNG được tạo.",
                "errors": [{"code": e.code, "location": e.location, "message": e.message} for e in result.errors],
            },
        )

    # Chuẩn hoá mã đề thi về ASCII thuần dù giáo viên tự đặt hay để hệ thống tự sinh —
    # tránh lỗi encode HTTP header khi xuất Excel (xem docstring _slugify_ascii) và
    # giúp mã đề dễ gõ/đọc miệng cho sinh viên hơn.
    manual_code = _slugify_ascii(exam_code or "")
    code = manual_code or _generate_exam_code(title)

    exam = Exam(
        exam_code=code,
        title=title.strip(),
        status=EXAM_STATUS_DRAFT,
        created_by=(created_by or "").strip() or None,
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
        "Đã tạo đề thi DRAFT '%s' (id=%d) với %d câu hợp lệ, %d lỗi bị bỏ qua",
        exam.exam_code, exam.id, result.valid_count, result.error_count,
    )

    return {
        "exam": exam.to_dict(include_questions=True, with_answers=True),
        "parse_errors": [
            {"code": e.code, "location": e.location, "message": e.message} for e in result.errors
        ],
    }


@router.get("")
def list_exams(db: Session = Depends(get_db), _auth: None = Depends(verify_proctor_token)):
    """[Cần token Giám thị] Danh sách toàn bộ đề thi đã tạo (mọi trạng thái), mới nhất trước."""
    exams = db.query(Exam).options(selectinload(Exam.questions)).order_by(Exam.created_at.desc()).all()
    return [e.to_dict() for e in exams]


@router.get("/{exam_id}")
def get_exam_detail(
    exam_id: int, db: Session = Depends(get_db), _auth: None = Depends(verify_proctor_token)
):
    """[Cần token Giám thị] Chi tiết 1 đề thi, bao gồm đáp án đúng — phục vụ xem trước/chỉnh sửa."""
    exam = (
        db.query(Exam)
        .options(selectinload(Exam.questions))
        .filter(Exam.id == exam_id)
        .first()
    )
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi")
    return exam.to_dict(include_questions=True, with_answers=True)


@router.post("/{exam_id}/publish")
def publish_exam(
    exam_id: int,
    payload: PublishRequest,
    db: Session = Depends(get_db),
    _auth: None = Depends(verify_proctor_token),
):
    """
    [Cần token Giám thị] Công bố đề thi: chuyển DRAFT -> PUBLISHED kèm cấu hình thời gian làm bài.
    Sau khi công bố, sinh viên có thể truy cập bằng đúng mã đề trong khung giờ quy định (nếu có).
    """
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi")
    if exam.status == EXAM_STATUS_CLOSED:
        raise HTTPException(status_code=400, detail="Đề thi đã đóng, không thể công bố lại")

    start_dt = _parse_iso_datetime(payload.start_time, "start_time")
    end_dt = _parse_iso_datetime(payload.end_time, "end_time")
    if start_dt and end_dt and end_dt <= start_dt:
        raise HTTPException(status_code=400, detail="Thời điểm đóng đề phải sau thời điểm mở đề")

    exam.duration_minutes = payload.duration_minutes
    exam.pass_score = payload.pass_score
    exam.shuffle_questions = payload.shuffle_questions
    exam.start_time = start_dt
    exam.end_time = end_dt
    exam.status = EXAM_STATUS_PUBLISHED

    db.commit()
    db.refresh(exam)
    logger.info("Đã công bố đề thi '%s' (id=%d)", exam.exam_code, exam.id)
    return exam.to_dict()


@router.delete("/{exam_id}")
def delete_exam(
    exam_id: int, db: Session = Depends(get_db), _auth: None = Depends(verify_proctor_token)
):
    """[Cần token Giám thị] Xóa đề thi — CHỈ cho phép khi chưa có sinh viên nào nộp bài."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
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
    logger.info("Đã xóa đề thi '%s' (id=%d)", exam.exam_code, exam_id)
    return {"message": "Đã xóa đề thi thành công"}


# ══════════════════════════════════════════════════════════
# PHẦN B — SINH VIÊN LÀM BÀI (KHÔNG cần token giám thị)
# ══════════════════════════════════════════════════════════

@router.get("/code/{exam_code}/take")
def take_exam(exam_code: str, db: Session = Depends(get_db)):
    """
    Lấy đề thi để sinh viên làm bài, theo đúng mã đề — TUYỆT ĐỐI KHÔNG trả đáp án đúng.
    Từ chối nếu đề chưa PUBLISHED, đã CLOSED, hoặc ngoài khung giờ start_time/end_time (nếu có cấu hình).
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
        "duration_minutes": exam.duration_minutes,
        "questions": [q.to_dict(with_answer=False) for q in questions],
    }


def _naive_utc_iso(dt: datetime) -> str:
    """Trả chuỗi ISO 8601 có hậu tố Z cho 1 datetime UTC không kèm múi giờ."""
    return dt.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


@router.post("/code/{exam_code}/start")
def start_exam(exam_code: str, payload: StartRequest, db: Session = Depends(get_db)):
    """
    Ghi nhận thời điểm sinh viên BẮT ĐẦU làm bài (lần đầu tiên) và trả về thời gian CÒN LẠI
    tính theo đồng hồ của server. Idempotent: gọi lại (tải lại trang, đổi thiết bị) không cấp
    lại thời gian từ đầu mà trả về phần còn lại — đồng hồ của điện thoại bị ngưng khi ứng dụng
    xuống nền cũng không còn làm sinh viên "được thêm giờ".

    Không chặn nộp bài trễ ở server: client vẫn tự nộp khi về 0 (giữ nguyên hành vi hiện tại).
    """
    exam = db.query(Exam).filter(Exam.exam_code == exam_code.strip().upper()).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi với mã này")
    if exam.status != EXAM_STATUS_PUBLISHED:
        raise HTTPException(status_code=403, detail="Đề thi chưa được công bố hoặc đã đóng")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if exam.start_time and now < exam.start_time:
        raise HTTPException(status_code=403, detail="Chưa đến thời gian mở đề thi")
    if exam.end_time and now > exam.end_time:
        raise HTTPException(status_code=403, detail="Đề thi đã hết thời gian làm bài")

    student_id = payload.student_id.strip()
    if not student_id:
        raise HTTPException(status_code=400, detail="Thiếu mã sinh viên")

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
            # 2 request "Bắt đầu" gần như đồng thời — lấy bản ghi đã được tạo bởi request kia
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
def submit_exam(exam_code: str, payload: SubmitRequest, db: Session = Depends(get_db)):
    """
    Sinh viên nộp bài làm — hệ thống CHẤM ĐIỂM TỰ ĐỘNG ngay lập tức trong cùng request này
    (đúng nguyên tắc thiết kế mục 2.2 đặc tả: không cần chờ tác vụ nền).

    Chỉ nhận 1 bài nộp duy nhất cho mỗi cặp (đề thi, sinh viên) — ràng buộc UNIQUE ở tầng CSDL
    đảm bảo an toàn ngay cả khi có request trùng gửi lên gần như đồng thời.
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

    student_id = payload.student_id.strip()
    if not student_id:
        raise HTTPException(status_code=400, detail="Thiếu mã sinh viên")

    # Chặn nộp trùng SỚM (kiểm tra ở tầng ứng dụng để trả lỗi rõ ràng, thân thiện) — ràng buộc
    # UNIQUE ở CSDL vẫn là lớp bảo vệ CUỐI CÙNG chống race condition khi có 2 request cùng lúc.
    existing = (
        db.query(ExamSubmission)
        .filter(ExamSubmission.exam_id == exam.id, ExamSubmission.student_id == student_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Sinh viên này đã nộp bài cho đề thi rồi, không thể nộp lại")

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

    # Giờ bắt đầu đã ghi ở server (nếu SV có gọi /start) — cột started_at trước đây luôn để trống
    start_record = (
        db.query(ExamStart)
        .filter(ExamStart.exam_id == exam.id, ExamStart.student_id == student_id)
        .first()
    )

    submission = ExamSubmission(
        exam_id=exam.id,
        student_id=student_id,
        student_name=(payload.student_name or "").strip() or None,
        started_at=start_record.started_at if start_record else None,
        submitted_at=datetime.now(timezone.utc).replace(tzinfo=None),
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
        # Trường hợp hiếm: 2 request nộp bài tới gần như đồng thời, request thứ 2 sẽ rơi vào đây
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
    """
    Dựng danh sách bảng điểm cho 1 đề thi, kèm cột "Số lần vi phạm" lấy từ bảng `violations`
    (module Giám sát) — liên kết MỀM theo student_id, không phải khóa ngoại chính thức
    (2 module độc lập, xem mục 5.5 đặc tả).

    Nếu đề thi có cấu hình start_time/end_time, chỉ đếm vi phạm xảy ra TRONG khung giờ thi đó
    (đúng ngữ cảnh ca thi) — nếu không có, đếm toàn bộ vi phạm của sinh viên (mọi thời điểm).
    """
    submissions = (
        db.query(ExamSubmission)
        .filter(ExamSubmission.exam_id == exam.id)
        .order_by(ExamSubmission.total_score.desc().nullslast())
        .all()
    )

    rows = []
    for s in submissions:
        violation_query = db.query(Violation).filter(Violation.student_id == s.student_id)
        if exam.start_time:
            violation_query = violation_query.filter(Violation.captured_at >= exam.start_time)
        if exam.end_time:
            violation_query = violation_query.filter(Violation.captured_at <= exam.end_time)
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
    exam_id: int, db: Session = Depends(get_db), _auth: None = Depends(verify_proctor_token)
):
    """[Cần token Giám thị] Bảng điểm toàn bộ sinh viên đã nộp bài của 1 đề, kèm số lần vi phạm."""
    exam = db.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy đề thi")

    return {
        "exam": exam.to_dict(),
        "results": _build_results_rows(exam, db),
    }


@router.get("/{exam_id}/export")
def export_exam_results(
    exam_id: int, db: Session = Depends(get_db), _auth: None = Depends(verify_proctor_token)
):
    """
    [Cần token Giám thị] Xuất file .xlsx bảng điểm của 1 đề thi (Chương 10.2 đặc tả).
    Tên file gợi ý: BangDiem_{exam_code}_{ngày xuất}.xlsx
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    exam = db.query(Exam).filter(Exam.id == exam_id).first()
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

    # Tự động canh độ rộng cột theo nội dung dài nhất mỗi cột
    for col_idx, header in enumerate(headers, start=1):
        max_len = max([len(str(header))] + [len(str(row[col_idx - 1])) for row in ws.iter_rows(min_row=2, values_only=True)])
        ws.column_dimensions[get_column_letter(col_idx)].width = max_len + 4

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"BangDiem_{exam.exam_code}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    # Lớp phòng vệ cuối: dù exam_code giờ luôn là ASCII (xem _slugify_ascii), vẫn encode an toàn
    # theo chuẩn RFC 5987 phòng trường hợp dữ liệu cũ/ngoại lệ còn sót ký tự Unicode — HTTP header
    # Content-Disposition dạng thường KHÔNG encode được ký tự ngoài latin-1, sẽ gây lỗi 500.
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii") or "BangDiem.xlsx"
    from urllib.parse import quote
    content_disposition = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition},
    )
