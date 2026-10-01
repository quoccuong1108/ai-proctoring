"""
EduShield AI — Database Layer
SQLAlchemy + SQLite storage for violation logs.

Bảng `violations` lưu metadata vi phạm + đường dẫn file ảnh snapshot.
Ảnh binary KHÔNG lưu trong DB — chỉ lưu đường dẫn tới file trên disk.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

logger = logging.getLogger("edushield.database")

# ──────────────────────────────────────────────────────────
# SQLAlchemy Engine & Session
# ──────────────────────────────────────────────────────────

DATABASE_URL = "sqlite:///edushield.db"

engine = create_engine(
    DATABASE_URL,
    # timeout: số giây SQLite tự chờ/thử lại trước khi báo lỗi "database is locked" —
    # quan trọng khi module Đề thi có thể nhận nhiều lượt NỘP BÀI gần như đồng thời
    # lúc gần hết giờ thi (khác với module Giám sát vốn chỉ ghi log rải rác).
    connect_args={"check_same_thread": False, "timeout": 15},
    echo=False,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """
    Bật chế độ WAL (Write-Ahead Logging) cho MỌI kết nối SQLite mới được mở.
    WAL cho phép các thao tác ĐỌC (GET danh sách, bảng điểm...) không bị chặn bởi
    thao tác GHI (nộp bài, ghi log vi phạm) đang diễn ra cùng lúc — giảm mạnh khả năng
    gặp lỗi khoá khi nhiều sinh viên nộp bài trong vài giây cuối giờ thi.

    Xem thêm phần thảo luận "SQLite vs PostgreSQL" — với quy mô 1 phòng thi/1 server,
    SQLite + WAL + busy_timeout là đủ đáp ứng; không cần đổi sang DB server riêng.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=15000")  # 15s — khớp với connect_args timeout ở trên
    cursor.execute("PRAGMA foreign_keys=ON")     # bật ràng buộc khóa ngoại (ON DELETE CASCADE)
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ──────────────────────────────────────────────────────────
# Base Model
# ──────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ──────────────────────────────────────────────────────────
# Hằng số trạng thái — Module Đề thi
# (Dùng string thay vì Enum cột DB để đơn giản hoá migration trên SQLite)
# ──────────────────────────────────────────────────────────

EXAM_STATUS_DRAFT = "DRAFT"
EXAM_STATUS_PUBLISHED = "PUBLISHED"
EXAM_STATUS_CLOSED = "CLOSED"

SUBMISSION_STATUS_IN_PROGRESS = "IN_PROGRESS"
SUBMISSION_STATUS_SUBMITTED = "SUBMITTED"
SUBMISSION_STATUS_AUTO_SUBMITTED = "AUTO_SUBMITTED"


# ──────────────────────────────────────────────────────────
# Violation Model
# ──────────────────────────────────────────────────────────

class Violation(Base):
    """
    Bảng ghi nhận vi phạm trong quá trình thi.

    Columns:
        id           — Primary key tự tăng
        student_id   — Mã sinh viên (e.g., "SV001")
        student_name — Họ và tên sinh viên (do sinh viên tự nhập lúc đăng nhập, có thể rỗng)
        violation_type — Loại vi phạm: NO_FACE, TURNING_HEAD, PHONE_DETECTED, etc.
        captured_at  — Thời điểm vi phạm xảy ra (ISO 8601, do client gửi lên)
        image_path   — Đường dẫn file ảnh snapshot trên disk, dạng snapshots/{student_id}/{filename}.jpg
                       (nullable khi đã bị xóa)
        created_at   — Thời điểm record được tạo trên server
    """

    __tablename__ = "violations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    student_id = Column(String(50), nullable=False, index=True)
    student_name = Column(String(150), nullable=True)
    violation_type = Column(String(50), nullable=False, index=True)
    captured_at = Column(DateTime, nullable=False, index=True)
    image_path = Column(String(500), nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return (
            f"<Violation(id={self.id}, student_id='{self.student_id}', "
            f"type='{self.violation_type}', captured_at='{self.captured_at}')>"
        )

    def to_dict(self, base_url: str = "") -> dict:
        """Serialize thành dict để trả về qua API."""
        image_url = None
        if self.image_path:
            # Ảnh được lưu theo cấu trúc snapshots/{student_folder}/{filename}.jpg — lấy đúng
            # 2 thành phần cuối của đường dẫn (thư mục SV + tên file) để dựng URL API tương ứng.
            norm_path = self.image_path.replace("\\", "/")
            parts = [p for p in norm_path.split("/") if p]
            rel = "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
            image_url = f"{base_url}/api/snapshots/{rel}"

        return {
            "id": self.id,
            "student_id": self.student_id,
            "student_name": self.student_name,
            "violation_type": self.violation_type,
            "captured_at": (self.captured_at.replace(tzinfo=timezone.utc) if self.captured_at.tzinfo is None else self.captured_at.astimezone(timezone.utc)).isoformat() if self.captured_at else None,
            "image_url": image_url,
            "image_path": self.image_path,
            "created_at": (self.created_at.replace(tzinfo=timezone.utc) if self.created_at.tzinfo is None else self.created_at.astimezone(timezone.utc)).isoformat() if self.created_at else None,
        }


# ──────────────────────────────────────────────────────────
# Exam Model — Đề thi
# ──────────────────────────────────────────────────────────

class Exam(Base):
    """
    Bảng lưu thông tin 1 đề thi trắc nghiệm, được tạo ra bằng cách Giảng viên upload file
    .xlsx/.docx theo mẫu quy định (xem exam_parser.py). Xem chi tiết Chương 5.1 đặc tả.

    Vòng đời trạng thái: DRAFT -> PUBLISHED -> CLOSED (đóng thủ công, chưa dùng ở bản này).
    """

    __tablename__ = "exams"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    exam_code = Column(String(50), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    # duration_minutes/pass_score chỉ có giá trị thật sau khi Publish; để mặc định hợp lý
    # cho đề còn ở trạng thái DRAFT (chưa cấu hình) để tránh giá trị NULL rải rác không cần thiết.
    duration_minutes = Column(Integer, nullable=True)
    pass_score = Column(Float, nullable=False, default=5.0)
    shuffle_questions = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default=EXAM_STATUS_DRAFT, index=True)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    questions = relationship(
        "Question",
        back_populates="exam",
        cascade="all, delete-orphan",
        order_by="Question.order_index",
    )
    submissions = relationship("ExamSubmission", back_populates="exam", cascade="all, delete-orphan")
    starts = relationship("ExamStart", back_populates="exam", cascade="all, delete-orphan")

    def to_dict(self, include_questions: bool = False, with_answers: bool = False) -> dict:
        data = {
            "id": self.id,
            "exam_code": self.exam_code,
            "title": self.title,
            "duration_minutes": self.duration_minutes,
            "total_questions": len(self.questions),
            "pass_score": self.pass_score,
            "shuffle_questions": self.shuffle_questions,
            "status": self.status,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_questions:
            data["questions"] = [q.to_dict(with_answer=with_answers) for q in self.questions]
        return data


class Question(Base):
    """1 câu hỏi trắc nghiệm 4 đáp án, thuộc về 1 đề thi (Chương 5.2 đặc tả)."""

    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True)
    order_index = Column(Integer, nullable=False, default=0)
    content = Column(String(2000), nullable=False)
    option_a = Column(String(1000), nullable=False)
    option_b = Column(String(1000), nullable=False)
    option_c = Column(String(1000), nullable=False)
    option_d = Column(String(1000), nullable=False)
    correct_option = Column(String(1), nullable=False)  # 'A' | 'B' | 'C' | 'D'
    score_weight = Column(Float, nullable=False, default=0.0)

    exam = relationship("Exam", back_populates="questions")

    def to_dict(self, with_answer: bool = False) -> dict:
        data = {
            "id": self.id,
            "order_index": self.order_index,
            "content": self.content,
            "option_a": self.option_a,
            "option_b": self.option_b,
            "option_c": self.option_c,
            "option_d": self.option_d,
            "score_weight": self.score_weight,
        }
        if with_answer:
            data["correct_option"] = self.correct_option
        return data


class ExamStart(Base):
    """
    Thời điểm sinh viên BẮT ĐẦU làm 1 đề thi, ghi nhận ở phía server (lần bấm "Bắt đầu làm bài"
    đầu tiên). Dùng để tính thời gian còn lại đáng tin cậy: đồng hồ ở trình duyệt/điện thoại có
    thể bị ngưng khi ứng dụng bị đẩy xuống nền, hoặc bị đặt lại khi sinh viên tải lại trang.

    Bảng mới, tự được tạo bởi init_db() (create_all) — không cần migrate dữ liệu cũ.
    Mỗi cặp (đề thi, sinh viên) chỉ có 1 dòng: bấm "Bắt đầu" lại (tải lại trang, đổi thiết bị)
    sẽ nhận về thời gian CÒN LẠI chứ không được cấp lại từ đầu.
    """

    __tablename__ = "exam_starts"
    __table_args__ = (
        UniqueConstraint("exam_id", "student_id", name="uq_exam_start_student"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id = Column(String(50), nullable=False, index=True)
    # Lưu dạng UTC không kèm múi giờ — cùng quy ước với start_time/end_time/submitted_at của module Đề thi.
    started_at = Column(DateTime, nullable=False)

    exam = relationship("Exam", back_populates="starts")


class ExamSubmission(Base):
    """
    Bài nộp của 1 sinh viên cho 1 đề thi (Chương 5.3 đặc tả).

    Ràng buộc UNIQUE(exam_id, student_id) ở tầng CSDL là lớp bảo vệ CUỐI CÙNG chống nộp
    trùng, kể cả khi có 2 request nộp bài của cùng 1 sinh viên tới gần như đồng thời
    (tầng ứng dụng ở exams_router.py cũng kiểm tra trước, nhưng chỉ CSDL mới đảm bảo tuyệt đối).
    """

    __tablename__ = "exam_submissions"
    __table_args__ = (
        UniqueConstraint("exam_id", "student_id", name="uq_exam_submission_student"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id = Column(String(50), nullable=False, index=True)
    student_name = Column(String(150), nullable=True)
    started_at = Column(DateTime, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    total_score = Column(Float, nullable=True)
    correct_count = Column(Integer, nullable=False, default=0)
    total_questions = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default=SUBMISSION_STATUS_SUBMITTED)

    exam = relationship("Exam", back_populates="submissions")
    answers = relationship(
        "SubmissionAnswer", back_populates="submission", cascade="all, delete-orphan"
    )


class SubmissionAnswer(Base):
    """Chi tiết 1 câu trả lời của sinh viên trong 1 bài nộp (Chương 5.4 đặc tả)."""

    __tablename__ = "submission_answers"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    submission_id = Column(
        Integer, ForeignKey("exam_submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    selected_option = Column(String(1), nullable=True)  # NULL nếu SV bỏ trống câu này
    is_correct = Column(Boolean, nullable=False, default=False)

    submission = relationship("ExamSubmission", back_populates="answers")


# ──────────────────────────────────────────────────────────
# Database Initialization
# ──────────────────────────────────────────────────────────

def init_db():
    """Tạo tất cả bảng nếu chưa tồn tại."""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database initialized successfully (SQLite: edushield.db)")
    except Exception as exc:
        logger.error("Failed to initialize database: %s", exc, exc_info=True)
        raise


def get_db():
    """
    FastAPI dependency — yield một session và tự đóng khi request kết thúc.

    Usage:
        @app.get("/api/violations")
        def list_violations(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
