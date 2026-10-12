"""Authentication for teacher accounts and approved student exam sessions."""

import hashlib
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from database import (
    ENROLLMENT_STATUS_APPROVED,
    ExamEnrollment,
    Teacher,
    TeacherSession,
    get_db,
)

logger = logging.getLogger("edushield.auth")

ALLOW_LEGACY_TOKEN = os.environ.get("ALLOW_LEGACY_TOKEN", "").strip() == "1"
PROCTOR_API_TOKEN = os.environ.get("PROCTOR_API_TOKEN", "")

_login_failures: Dict[str, List[float]] = {}
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 60
TEACHER_CODE_PATTERN = re.compile(r"^GV-[A-Z0-9]{4}$")


def normalize_teacher_code(teacher_code: str) -> str:
    code = teacher_code.strip().upper()
    if not TEACHER_CODE_PATTERN.fullmatch(code):
        raise HTTPException(
            status_code=422,
            detail="Mã giảng viên phải đúng định dạng GV-xxxx, ví dụ GV-2026.",
        )
    return code


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """Hash a password with scrypt and a random salt."""
    salt = salt or secrets.token_hex(16)
    password_hash = hashlib.scrypt(
        password.encode("utf-8"),
        salt=bytes.fromhex(salt),
        n=2**14,
        r=8,
        p=1,
        dklen=64,
    ).hex()
    return password_hash, salt


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    """Verify scrypt hashes, retaining compatibility with existing PBKDF2 hashes."""
    try:
        if len(expected_hash) == 128:
            password_hash, _ = hash_password(password, salt)
        else:
            password_hash = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt),
                100_000,
            ).hex()
        return secrets.compare_digest(password_hash, expected_hash)
    except (TypeError, ValueError):
        return False


def hash_token(token: str) -> str:
    """Return the SHA-256 digest stored for an authentication token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def check_login_rate_limit(ip: str) -> None:
    """Allow at most five failed login attempts per IP in a rolling minute."""
    now = time.time()
    attempts = [attempt for attempt in _login_failures.get(ip, []) if now - attempt < LOCKOUT_SECONDS]
    _login_failures[ip] = attempts
    if len(attempts) >= MAX_LOGIN_ATTEMPTS:
        remaining_seconds = max(1, int(LOCKOUT_SECONDS - (now - attempts[0])))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Quá nhiều lần đăng nhập không thành công. Vui lòng thử lại sau {remaining_seconds} giây.",
        )


def record_login_failure(ip: str) -> None:
    now = time.time()
    attempts = _login_failures.get(ip, [])
    _login_failures[ip] = [
        attempt for attempt in attempts if now - attempt < LOCKOUT_SECONDS
    ] + [now]


def record_login_success(ip: str) -> None:
    _login_failures.pop(ip, None)


def create_teacher_session(
    db: Session, teacher_id: int, ip: Optional[str] = None
) -> Tuple[str, datetime]:
    """Create a random 12-hour teacher token and store only its SHA-256 digest."""
    raw_token = secrets.token_urlsafe(32)
    now_utc = datetime.now(timezone.utc)
    expires_at = now_utc + timedelta(hours=12)
    session = TeacherSession(
        teacher_id=teacher_id,
        token_hash=hash_token(raw_token),
        created_at=now_utc,
        expires_at=expires_at,
        ip=ip,
    )
    db.add(session)
    db.commit()
    return raw_token, expires_at


def extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Accept only Authorization: Bearer <token>."""
    if not authorization:
        return None
    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def _get_legacy_admin(db: Session) -> Teacher:
    admin = db.query(Teacher).filter(Teacher.teacher_code == "GV-ADMIN").first()
    if admin:
        return admin
    password_hash, salt = hash_password(secrets.token_urlsafe(32))
    admin = Teacher(
        teacher_code="GV-ADMIN",
        full_name="Giảng viên Quản trị",
        password_hash=password_hash,
        password_salt=salt,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def get_current_teacher(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Teacher:
    """Resolve and return the teacher authenticated by an Authorization Bearer token."""
    supplied_token = extract_bearer_token(authorization)
    if not supplied_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Yêu cầu Authorization: Bearer với phiên đăng nhập Giảng viên.",
        )

    session = (
        db.query(TeacherSession)
        .filter(TeacherSession.token_hash == hash_token(supplied_token))
        .first()
    )
    if session:
        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at > datetime.now(timezone.utc):
            return session.teacher

    if (
        ALLOW_LEGACY_TOKEN
        and PROCTOR_API_TOKEN
        and secrets.compare_digest(supplied_token, PROCTOR_API_TOKEN)
    ):
        return _get_legacy_admin(db)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Phiên làm việc hết hạn hoặc không hợp lệ. Vui lòng đăng nhập lại.",
    )


def get_exam_session(
    x_exam_session: Optional[str] = Header(default=None, alias="X-Exam-Session"),
    db: Session = Depends(get_db),
) -> ExamEnrollment:
    """Resolve a student session that was approved by a teacher."""
    if not x_exam_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thiếu mã phiên thi hợp lệ (header X-Exam-Session).",
        )

    enrollment = (
        db.query(ExamEnrollment)
        .filter(ExamEnrollment.session_token_hash == hash_token(x_exam_session.strip()))
        .first()
    )
    if not enrollment:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Phiên thi không tồn tại hoặc không hợp lệ.",
        )
    if enrollment.status != ENROLLMENT_STATUS_APPROVED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Phiên thi không ở trạng thái được duyệt (Trạng thái hiện tại: {enrollment.status}).",
        )
    if not enrollment.session_token_issued:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Phiên thi chưa được cấp cho sinh viên.",
        )
    return enrollment
