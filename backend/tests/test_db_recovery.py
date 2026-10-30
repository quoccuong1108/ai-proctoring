import os
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import URL, create_engine
from sqlalchemy.exc import DatabaseError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import backup_database, check_database_integrity, init_db
from recover_db import recover_database


def _sqlite_engine(path):
    return create_engine(URL.create("sqlite", database=str(path)))


def _overwrite_page(path, page_number, page_size):
    with path.open("r+b") as database_file:
        database_file.seek(page_number * page_size)
        database_file.write(b"\x00" * 16)


def test_quick_check_passes_for_healthy_database(tmp_path):
    database_path = tmp_path / "healthy.db"
    db_engine = _sqlite_engine(database_path)
    try:
        with sqlite3.connect(database_path) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
            connection.execute("INSERT INTO sample VALUES (1)")
        assert check_database_integrity(db_engine) == "ok"
    finally:
        db_engine.dispose()


def test_startup_stops_when_database_is_corrupt(tmp_path):
    database_path = tmp_path / "corrupt.db"
    db_engine = _sqlite_engine(database_path)
    try:
        with db_engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA page_size=65536")
            conn.exec_driver_sql("CREATE TABLE records (id INTEGER PRIMARY KEY, data TEXT)")
            conn.exec_driver_sql(
                "INSERT INTO records (data) VALUES "
                + ", ".join(f"('{index:04d}' || hex(randomblob(1500)))" for index in range(16))
            )

        with sqlite3.connect(database_path) as connection:
            page_size = connection.execute("PRAGMA page_size").fetchone()[0]
            assert connection.execute("PRAGMA page_count").fetchone()[0] == 2
        db_engine.dispose()
        _overwrite_page(database_path, 1, page_size)

        with pytest.raises(RuntimeError, match="Không thể kiểm tra"):
            init_db(db_engine)
    finally:
        db_engine.dispose()


def test_recovery_copies_tables_readable_from_partially_corrupt_database(tmp_path):
    source_path = tmp_path / "damaged.db"
    destination_path = tmp_path / "recovered.db"
    with sqlite3.connect(source_path) as connection:
        connection.execute("CREATE TABLE damaged (id INTEGER PRIMARY KEY, data TEXT)")
        connection.executemany(
            "INSERT INTO damaged (data) VALUES (?)",
            [(f"{index:04d}" + "x" * 1800,) for index in range(120)],
        )
        connection.execute(
            "CREATE TABLE readable (id INTEGER PRIMARY KEY, value TEXT)"
        )
        connection.execute("INSERT INTO readable VALUES (1, 'còn đọc được')")
        connection.commit()
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]

    _overwrite_page(source_path, 2, page_size)
    _, integrity, output_path = recover_database(source_path, destination_path)

    assert output_path == destination_path
    assert integrity == ["ok"]
    with sqlite3.connect(destination_path) as recovered:
        assert recovered.execute("SELECT value FROM readable").fetchone() == (
            "còn đọc được",
        )


def test_backup_uses_sqlite_backup_api_and_keeps_seven_files(tmp_path):
    database_path = tmp_path / "edushield.db"
    db_engine = _sqlite_engine(database_path)
    backup_dir = tmp_path / "db_backups"
    try:
        with db_engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE sample (value TEXT)")
            conn.exec_driver_sql("INSERT INTO sample VALUES ('backup data')")

        backup_dir.mkdir()
        for index in range(8):
            old_backup = backup_dir / f"edushield-20000101-{index:06d}.db"
            old_backup.write_bytes(b"old backup")
            os.utime(old_backup, (index, index))

        backup_path = backup_database(db_engine)
        assert backup_path.parent == backup_dir
        assert len(list(backup_dir.glob("edushield-????????-??????.db"))) == 7
        with sqlite3.connect(backup_path) as backup:
            assert backup.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            assert backup.execute("SELECT value FROM sample").fetchone() == (
                "backup data",
            )
    finally:
        db_engine.dispose()


def test_database_error_api_response_is_503_and_rolls_back_session():
    from main import database_error_handler

    sessions = []

    class MockSession:
        def __init__(self):
            self.rolled_back = False

        def rollback(self):
            self.rolled_back = True

    api = FastAPI()
    api.add_exception_handler(DatabaseError, database_error_handler)

    @api.get("/db-error")
    async def raise_database_error(request: Request):
        session = MockSession()
        sessions.append(session)
        request.state.db = session
        raise DatabaseError("SELECT 1", {}, sqlite3.DatabaseError("corrupt"))

    with TestClient(api) as client:
        response = client.get("/db-error")

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Cơ sở dữ liệu đang gặp sự cố, vui lòng liên hệ quản trị viên"
    )
    assert sessions[0].rolled_back
