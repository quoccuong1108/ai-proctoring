"""Tạo tài khoản giảng viên với mật khẩu nhập an toàn qua getpass."""

import getpass
import sys
from datetime import datetime, timezone

from auth import TEACHER_CODE_PATTERN, hash_password
from database import SessionLocal, Teacher, init_db


def main() -> int:
    if len(sys.argv) != 3:
        print('Cách dùng: python create_teacher.py <ma_gv> "<Họ tên>"')
        return 2

    code = sys.argv[1].strip().upper()
    full_name = sys.argv[2].strip()
    if not TEACHER_CODE_PATTERN.fullmatch(code):
        print("Lỗi: Mã giảng viên phải đúng định dạng GV-xxxx, ví dụ GV-2026.")
        return 2
    if not full_name:
        print("Lỗi: Họ và tên không được để trống.")
        return 2

    password = getpass.getpass("Nhập mật khẩu: ")
    confirmation = getpass.getpass("Nhập lại mật khẩu: ")
    if password != confirmation:
        print("Lỗi: Mật khẩu nhập lại không khớp.")
        return 2
    if len(password) < 6:
        print("Lỗi: Mật khẩu phải có ít nhất 6 ký tự.")
        return 2

    init_db()
    db = SessionLocal()
    try:
        if db.query(Teacher.id).filter(Teacher.teacher_code == code).first():
            print(f"Lỗi: Mã giảng viên {code} đã tồn tại.")
            return 1

        password_hash, password_salt = hash_password(password)
        teacher = Teacher(
            teacher_code=code,
            full_name=full_name,
            password_hash=password_hash,
            password_salt=password_salt,
            created_at=datetime.now(timezone.utc),
        )
        db.add(teacher)
        db.commit()
        print(f"Đã tạo tài khoản giảng viên {code} - {full_name}.")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
