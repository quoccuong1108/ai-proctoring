"""
EduShield AI — Database Layer
SQLAlchemy + SQLite storage for violation logs.

Bảng `violations` lưu metadata vi phạm + đường dẫn file ảnh snapshot.
Ảnh binary KHÔNG lưu trong DB — chỉ lưu đường dẫn tới file trên disk.
"""

import logging
import os
import sqlite3
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    text,
    UniqueConstraint,
    URL,
    create_engine,
    event,
    inspect,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

logger = logging.getLogger("edushield.database")

# ──────────────────────────────────────────────────────────
# SQLAlchemy Engine & Session
# ──────────────────────────────────────────────────────────

DATABASE_URL = URL.create(
    "sqlite",
    database=os.path.join(os.path.dirname(os.path.abspath(__file__)), "edushield.db"),
)

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
# Hằng số trạng thái — Module Đề thi & Ghi danh
# (Dùng string thay vì Enum cột DB để đơn giản hoá migration trên SQLite)
# ──────────────────────────────────────────────────────────

EXAM_STATUS_DRAFT = "DRAFT"
EXAM_STATUS_PUBLISHED = "PUBLISHED"
EXAM_STATUS_CLOSED = "CLOSED"

SUBMISSION_STATUS_IN_PROGRESS = "IN_PROGRESS"
SUBMISSION_STATUS_SUBMITTED = "SUBMITTED"
SUBMISSION_STATUS_AUTO_SUBMITTED = "AUTO_SUBMITTED"

ENROLLMENT_STATUS_PENDING = "PENDING"
ENROLLMENT_STATUS_APPROVED = "APPROVED"
ENROLLMENT_STATUS_REJECTED = "REJECTED"
ENROLLMENT_STATUS_REVOKED = "REVOKED"


# ──────────────────────────────────────────────────────────
# Teacher & Session Models — Tài khoản & Phiên Giảng viên
# ──────────────────────────────────────────────────────────

class Teacher(Base):
    """
    Bảng lưu thông tin tài khoản Giảng viên / Giám thị.
    """

    __tablename__ = "teachers"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    teacher_code = Column(String(50), unique=True, nullable=False, index=True)
    full_name = Column(String(150), nullable=False)
    password_hash = Column(String(255), nullable=False)
    password_salt = Column(String(64), nullable=False)
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    sessions = relationship("TeacherSession", back_populates="teacher", cascade="all, delete-orphan")
    exams = relationship("Exam", back_populates="teacher")

    def __repr__(self):
        return f"<Teacher(id={self.id}, code='{self.teacher_code}', name='{self.full_name}')>"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "teacher_code": self.teacher_code,
            "full_name": self.full_name,
            "created_at": (
                self.created_at.replace(tzinfo=timezone.utc)
                if self.created_at.tzinfo is None
                else self.created_at.astimezone(timezone.utc)
            ).isoformat() if self.created_at else None,
        }


class TeacherSession(Base):
    """
    Bảng lưu phiên đăng nhập của Giảng viên.
    Token thực tế lưu dạng SHA-256 hash để bảo mật.
    """

    __tablename__ = "teacher_sessions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at = Column(DateTime, nullable=False, index=True)
    ip = Column(String(50), nullable=True)

    teacher = relationship("Teacher", back_populates="sessions")


# ──────────────────────────────────────────────────────────
# Violation Model
# ──────────────────────────────────────────────────────────

class Violation(Base):
    """
    Bảng ghi nhận vi phạm trong quá trình thi.

    Columns:
        id           — Primary key tự tăng
        student_id   — Mã sinh viên (e.g., "SV001")
        student_name — Họ và tên khai báo trong yêu cầu vào thi
        violation_type — Loại vi phạm: NO_FACE, TURNING_HEAD, PHONE_DETECTED, etc.
        captured_at  — Thời điểm vi phạm xảy ra (ISO 8601, do client gửi lên)
        image_path   — Đường dẫn file ảnh snapshot trên disk, dạng snapshots/{student_id}/{filename}.jpg
                       (nullable khi đã bị xóa)
        created_at   — Thời điểm record được tạo trên server
        exam_id      — ID đề thi liên kết (nullable)
        enrollment_id— ID lượt ghi danh liên kết (nullable)
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
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="SET NULL"), nullable=True, index=True)
    enrollment_id = Column(Integer, ForeignKey("exam_enrollments.id", ondelete="SET NULL"), nullable=True, index=True)

    exam = relationship("Exam", back_populates="violations")
    enrollment = relationship("ExamEnrollment", back_populates="violations")

    def __repr__(self):
        return (
            f"<Violation(id={self.id}, student_id='{self.student_id}', "
            f"type='{self.violation_type}', captured_at='{self.captured_at}')>"
        )

    def to_dict(self, base_url: str = "") -> dict:
        """Serialize thành dict để trả về qua API."""
        image_url = None
        if self.image_path:
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
            "exam_id": self.exam_id,
            "enrollment_id": self.enrollment_id,
        }


# ──────────────────────────────────────────────────────────
# Exam Model — Đề thi
# ──────────────────────────────────────────────────────────

class Exam(Base):
    """
    Bảng lưu thông tin 1 đề thi trắc nghiệm.
    Vòng đời trạng thái: DRAFT -> PUBLISHED -> CLOSED.
    """

    __tablename__ = "exams"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    exam_code = Column(String(50), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    subject = Column(
        String(100),
        nullable=False,
        default="Chưa phân môn",
        server_default="Chưa phân môn",
        index=True,
    )
    teacher_id = Column(Integer, ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True, index=True)
    join_open_minutes = Column(Integer, nullable=False, default=15, server_default="15")
    duration_minutes = Column(Integer, nullable=True)
    pass_score = Column(Float, nullable=False, default=5.0)
    shuffle_questions = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default=EXAM_STATUS_DRAFT, index=True)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    created_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    teacher = relationship("Teacher", back_populates="exams")
    questions = relationship(
        "Question",
        back_populates="exam",
        cascade="all, delete-orphan",
        order_by="Question.order_index",
    )
    submissions = relationship("ExamSubmission", back_populates="exam", cascade="all, delete-orphan")
    starts = relationship("ExamStart", back_populates="exam", cascade="all, delete-orphan")
    enrollments = relationship("ExamEnrollment", back_populates="exam", cascade="all, delete-orphan")
    violations = relationship("Violation", back_populates="exam")

    def to_dict(self, include_questions: bool = False, with_answers: bool = False) -> dict:
        data = {
            "id": self.id,
            "exam_code": self.exam_code,
            "title": self.title,
            "subject": self.subject or "Chưa phân môn",
            "teacher_id": self.teacher_id,
            "teacher_name": self.teacher.full_name if self.teacher else (self.created_by or "Giảng viên"),
            "join_open_minutes": self.join_open_minutes,
            "duration_minutes": self.duration_minutes,
            "total_questions": len(self.questions),
            "pass_score": self.pass_score,
            "shuffle_questions": self.shuffle_questions,
            "status": self.status,
            "start_time": (
                self.start_time.replace(tzinfo=timezone.utc)
                if self.start_time and self.start_time.tzinfo is None
                else self.start_time.astimezone(timezone.utc)
            ).isoformat() if self.start_time else None,
            "end_time": (
                self.end_time.replace(tzinfo=timezone.utc)
                if self.end_time and self.end_time.tzinfo is None
                else self.end_time.astimezone(timezone.utc)
            ).isoformat() if self.end_time else None,
            "created_by": self.created_by,
            "created_at": (
                self.created_at.replace(tzinfo=timezone.utc)
                if self.created_at and self.created_at.tzinfo is None
                else self.created_at.astimezone(timezone.utc)
            ).isoformat() if self.created_at else None,
        }
        if include_questions:
            data["questions"] = [q.to_dict(with_answer=with_answers) for q in self.questions]
        return data


class Question(Base):
    """1 câu hỏi trắc nghiệm 4 đáp án, thuộc về 1 đề thi."""

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
    Thời điểm sinh viên BẮT ĐẦU làm 1 đề thi, ghi nhận ở phía server.
    """

    __tablename__ = "exam_starts"
    __table_args__ = (
        UniqueConstraint("exam_id", "student_id", name="uq_exam_start_student"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id = Column(String(50), nullable=False, index=True)
    started_at = Column(DateTime, nullable=False)

    exam = relationship("Exam", back_populates="starts")


class ExamSubmission(Base):
    """
    Bài nộp của 1 sinh viên cho 1 đề thi.
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
    """Chi tiết 1 câu trả lời của sinh viên trong 1 bài nộp."""

    __tablename__ = "submission_answers"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    submission_id = Column(
        Integer, ForeignKey("exam_submissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    selected_option = Column(String(1), nullable=True)
    is_correct = Column(Boolean, nullable=False, default=False)

    submission = relationship("ExamSubmission", back_populates="answers")


class ExamEnrollment(Base):
    """
    Ghi danh xin vào thi của Sinh viên đối với 1 Đề thi cụ thể.
    Trạng thái: PENDING -> APPROVED / REJECTED / REVOKED
    """

    __tablename__ = "exam_enrollments"
    __table_args__ = (
        UniqueConstraint("exam_id", "student_id", name="uq_exam_student_enrollment"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id = Column(String(50), nullable=False, index=True)
    student_name = Column(String(150), nullable=False)
    status = Column(String(20), nullable=False, default=ENROLLMENT_STATUS_PENDING, index=True)
    session_token_hash = Column(String(64), unique=True, nullable=True, index=True)
    requested_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    decided_at = Column(DateTime, nullable=True)
    decided_by = Column(Integer, ForeignKey("teachers.id", ondelete="SET NULL"), nullable=True)
    reject_reason = Column(String(255), nullable=True)
    device_info = Column(String(255), nullable=True)
    ip = Column(String(50), nullable=True)
    request_token_hash = Column(String(64), unique=True, nullable=True, index=True)
    session_token_issued = Column(Boolean, nullable=False, default=False, server_default="0")

    exam = relationship("Exam", back_populates="enrollments")
    violations = relationship("Violation", back_populates="enrollment")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "exam_id": self.exam_id,
            "student_id": self.student_id,
            "student_name": self.student_name,
            "status": self.status,
            "requested_at": (
                self.requested_at.replace(tzinfo=timezone.utc)
                if self.requested_at.tzinfo is None
                else self.requested_at.astimezone(timezone.utc)
            ).isoformat() if self.requested_at else None,
            "decided_at": (
                self.decided_at.replace(tzinfo=timezone.utc)
                if self.decided_at and self.decided_at.tzinfo is None
                else self.decided_at.astimezone(timezone.utc)
            ).isoformat() if self.decided_at else None,
            "decided_by": self.decided_by,
            "reject_reason": self.reject_reason,
            "device_info": self.device_info,
            "ip": self.ip,
        }


# ──────────────────────────────────────────────────────────
# Database Migration Helper
# ──────────────────────────────────────────────────────────

def _backup_database(db_engine):
    with db_engine.connect() as conn:
        database_path = conn.exec_driver_sql("PRAGMA database_list").fetchone()[2]
        if not database_path or not os.path.isfile(database_path):
            return

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = f"{database_path}.pre-migration-{timestamp}.bak"
        backup_db = sqlite3.connect(backup_path)
        try:
            conn.connection.driver_connection.backup(backup_db)
        finally:
            backup_db.close()
        logger.info("Database backup created before migration: %s", backup_path)


def _database_needs_update(db_engine):
    inspector = inspect(db_engine)
    tables = set(inspector.get_table_names())
    if not tables:
        return False

    if set(Base.metadata.tables) - tables:
        return True

    required_columns = {
        "exams": {"subject", "teacher_id", "join_open_minutes"},
        "violations": {"exam_id", "enrollment_id"},
        "exam_enrollments": {"request_token_hash", "session_token_issued"},
    }
    for table, required in required_columns.items():
        if table in tables:
            columns = {column["name"] for column in inspector.get_columns(table)}
            if required - columns:
                return True
    exam_columns = {
        column["name"] for column in inspector.get_columns("exams")
    } if "exams" in tables else set()
    if {"subject", "teacher_id"} <= exam_columns:
        with db_engine.connect() as conn:
            needs_subject_backfill = conn.exec_driver_sql(
                "SELECT 1 FROM exams WHERE subject IS NULL OR TRIM(subject) = '' "
                "OR (subject = 'Chung' AND teacher_id IS NULL) LIMIT 1"
            ).first()
        if needs_subject_backfill:
            return True
    return False


def migrate_db(db_engine, create_backup=True):
    """
    Tự động cập nhật schema (ALTER TABLE) cho SQLite khi nâng cấp phiên bản
    mà không làm mất dữ liệu đã có.
    """
    with db_engine.connect() as conn:
        res = conn.exec_driver_sql("PRAGMA table_info(exams)").fetchall()
        exam_cols = {row[1] for row in res}
        res_v = conn.exec_driver_sql("PRAGMA table_info(violations)").fetchall()
        v_cols = {row[1] for row in res_v}
        enrollment_cols = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(exam_enrollments)").fetchall()
        }

        migrations = []
        subject_added = False
        if exam_cols:
            if "subject" not in exam_cols:
                migrations.append(
                    ("exams", "subject", "VARCHAR(100) NOT NULL DEFAULT 'Chưa phân môn'")
                )
                subject_added = True
            if "teacher_id" not in exam_cols:
                migrations.append(("exams", "teacher_id", "INTEGER REFERENCES teachers(id)"))
            if "join_open_minutes" not in exam_cols:
                migrations.append(
                    ("exams", "join_open_minutes", "INTEGER NOT NULL DEFAULT 15")
                )

        if v_cols:
            if "exam_id" not in v_cols:
                migrations.append(("violations", "exam_id", "INTEGER REFERENCES exams(id)"))
            if "enrollment_id" not in v_cols:
                migrations.append(
                    ("violations", "enrollment_id", "INTEGER REFERENCES exam_enrollments(id)")
                )

        request_token_added = False
        if enrollment_cols:
            if "request_token_hash" not in enrollment_cols:
                migrations.append(
                    ("exam_enrollments", "request_token_hash", "VARCHAR(64)")
                )
                request_token_added = True
            if "session_token_issued" not in enrollment_cols:
                migrations.append(
                    ("exam_enrollments", "session_token_issued", "BOOLEAN NOT NULL DEFAULT 0")
                )

        needs_subject_backfill = False
        if {"subject", "teacher_id"} <= exam_cols:
            needs_subject_backfill = conn.exec_driver_sql(
                "SELECT 1 FROM exams WHERE subject IS NULL OR TRIM(subject) = '' "
                "OR (subject = 'Chung' AND teacher_id IS NULL) LIMIT 1"
            ).first() is not None

        if (migrations or needs_subject_backfill) and create_backup:
            conn.rollback()
            _backup_database(db_engine)
        for table, column, definition in migrations:
            logger.info("Migrating %s: ADD COLUMN %s", table, column)
            conn.exec_driver_sql(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )
        if subject_added:
            conn.execute(
                text("UPDATE exams SET subject = 'Chưa phân môn'")
            )
        elif exam_cols and "subject" in exam_cols:
            conn.execute(
                text(
                    "UPDATE exams SET subject = 'Chưa phân môn' "
                    "WHERE subject IS NULL OR TRIM(subject) = '' "
                    "OR (subject = 'Chung' AND teacher_id IS NULL)"
                )
            )
        if request_token_added:
            conn.execute(
                text(
                    "UPDATE exam_enrollments "
                    "SET request_token_hash = session_token_hash, session_token_hash = NULL, "
                    "session_token_issued = 0 "
                    "WHERE session_token_hash IS NOT NULL"
                )
            )
        if enrollment_cols:
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "ix_exam_enrollments_request_token_hash "
                "ON exam_enrollments (request_token_hash)"
            )
        conn.commit()


# ──────────────────────────────────────────────────────────
# Database Initialization
# ──────────────────────────────────────────────────────────

def init_db():
    """Tạo tất cả bảng nếu chưa tồn tại và chạy migrate schema."""
    try:
        if _database_needs_update(engine):
            _backup_database(engine)
        Base.metadata.create_all(bind=engine)
        migrate_db(engine, create_backup=False)
        logger.info("Database initialized & migrated successfully (SQLite: edushield.db)")
    except Exception as exc:
        logger.error("Failed to initialize database: %s", exc, exc_info=True)
        raise


def get_db():
    """
    FastAPI dependency — yield một session và tự đóng khi request kết thúc.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
