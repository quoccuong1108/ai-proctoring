"""Cứu dữ liệu từ edushield.db sang một file mới, không sửa file nguồn."""

import argparse
import sqlite3
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE = BACKEND_DIR / "edushield.db"
DEFAULT_DESTINATION = BACKEND_DIR / "edushield_recovered.db"


def _quote_identifier(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _copy_table(source, destination, table_name, table_sql):
    quoted_table = _quote_identifier(table_name)
    try:
        destination.execute(table_sql)
        destination.commit()
        columns = [
            row[1]
            for row in source.execute(
                f"PRAGMA table_info({quoted_table})"
            ).fetchall()
        ]
        if not columns:
            raise sqlite3.DatabaseError("Không đọc được cấu trúc cột của bảng")

        quoted_columns = ", ".join(_quote_identifier(column) for column in columns)
        placeholders = ", ".join("?" for _ in columns)
        insert_sql = (
            f"INSERT INTO {quoted_table} ({quoted_columns}) "
            f"VALUES ({placeholders})"
        )

        try:
            count = 0
            for row in source.execute(
                f"SELECT {quoted_columns} FROM {quoted_table}"
            ):
                destination.execute(insert_sql, row)
                count += 1
            destination.commit()
            return count, None
        except sqlite3.DatabaseError as bulk_error:
            destination.rollback()
            rowids = []
            rowid_error = None
            try:
                cursor = source.execute(f"SELECT rowid FROM {quoted_table}")
                while True:
                    row = cursor.fetchone()
                    if row is None:
                        break
                    rowids.append(row[0])
            except sqlite3.DatabaseError as exc:
                rowid_error = exc

            count = 0
            row_errors = []
            for rowid in rowids:
                try:
                    destination.execute("SAVEPOINT recover_row")
                    row = source.execute(
                        f"SELECT {quoted_columns} FROM {quoted_table} WHERE rowid = ?",
                        (rowid,),
                    ).fetchone()
                    if row is None:
                        destination.execute("RELEASE SAVEPOINT recover_row")
                        continue
                    destination.execute(insert_sql, row)
                    destination.execute("RELEASE SAVEPOINT recover_row")
                    count += 1
                except sqlite3.DatabaseError as exc:
                    destination.execute("ROLLBACK TO SAVEPOINT recover_row")
                    destination.execute("RELEASE SAVEPOINT recover_row")
                    row_errors.append(f"rowid {rowid}: {exc}")
            destination.commit()

            details = [f"lỗi khi sao chép tuần tự: {bulk_error}"]
            if rowid_error:
                details.append(f"không đọc hết rowid: {rowid_error}")
            if row_errors:
                details.append("; ".join(row_errors[:5]))
            return count, "; ".join(details)
    except sqlite3.DatabaseError as exc:
        destination.rollback()
        return 0, str(exc)


def recover_database(source_path=DEFAULT_SOURCE, destination_path=DEFAULT_DESTINATION):
    """Sao chép các bảng còn đọc được sang file đích mới."""
    source_path = Path(source_path).resolve()
    destination_path = Path(destination_path).resolve()
    if destination_path.exists():
        raise FileExistsError(f"File đích đã tồn tại, không ghi đè: {destination_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)

    source_uri = f"{source_path.as_uri()}?mode=ro"
    source = sqlite3.connect(source_uri, uri=True)
    destination = sqlite3.connect(str(destination_path))
    results = {}

    try:
        destination.execute("PRAGMA foreign_keys=OFF")
        try:
            tables = source.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            print(f"[LỖI] Không đọc được danh sách bảng: {exc}")
            tables = []

        for table_name, table_sql in tables:
            if not table_sql:
                results[table_name] = (0, "Không tìm thấy câu SQL tạo bảng")
                print(f"[LỖI] {table_name}: {results[table_name][1]}")
                continue
            count, error = _copy_table(
                source, destination, table_name, table_sql
            )
            results[table_name] = (count, error)
            if error:
                print(f"[LỖI] {table_name}: cứu được {count} dòng; {error}")
            else:
                print(f"[OK] {table_name}: {count} dòng")

        try:
            indexes = source.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type = 'index' AND sql IS NOT NULL ORDER BY name"
            ).fetchall()
        except sqlite3.DatabaseError as exc:
            indexes = []
            print(f"[LỖI] Không đọc được danh sách index: {exc}")

        for index_name, index_sql in indexes:
            try:
                destination.execute(index_sql)
                destination.commit()
            except sqlite3.DatabaseError as exc:
                destination.rollback()
                print(f"[LỖI] index {index_name}: {exc}")

        try:
            integrity = destination.execute("PRAGMA integrity_check").fetchall()
            for row in integrity:
                print(f"PRAGMA integrity_check: {row[0]}")
        except sqlite3.DatabaseError as exc:
            integrity = [(str(exc),)]
            print(f"PRAGMA integrity_check: {exc}")
    finally:
        source.close()
        destination.close()

    return results, [row[0] for row in integrity], destination_path


def main():
    parser = argparse.ArgumentParser(
        description="Cứu các bảng còn đọc được sang edushield_recovered.db."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    arguments = parser.parse_args()
    _, integrity, _ = recover_database(arguments.source, arguments.destination)
    return 0 if integrity == ["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
