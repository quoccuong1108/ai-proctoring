"""
EduShield AI — Scheduler Layer
APScheduler background task: Tự động dọn dẹp ảnh snapshot quá 24 giờ.

Job chạy mỗi 1 giờ:
  1. Query violations có captured_at > 24h VÀ image_path != null
  2. Xóa file ảnh khỏi thư mục snapshots/
  3. Cập nhật image_path = null trong DB (giữ lại metadata log)
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database import SessionLocal, Violation, backup_database

logger = logging.getLogger("edushield.scheduler")

# ──────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────

CLEANUP_INTERVAL_HOURS = 1       # Quét mỗi 1 giờ
IMAGE_RETENTION_HOURS = 24       # Giữ ảnh tối đa 24 giờ
BACKUP_INTERVAL_HOURS = 6
SNAPSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")

# ──────────────────────────────────────────────────────────
# Cleanup Job
# ──────────────────────────────────────────────────────────

def cleanup_expired_snapshots():
    """
    Xóa ảnh snapshot quá hạn (> 24h kể từ captured_at).

    Quy trình:
      1. Tính mốc thời gian cutoff = now - 24h
      2. Query tất cả violations có captured_at < cutoff VÀ image_path IS NOT NULL
      3. Với mỗi record: xóa file ảnh trên disk, set image_path = None
      4. Commit batch
    """
    db = SessionLocal()
    deleted_count = 0
    error_count = 0

    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=IMAGE_RETENTION_HOURS)
        logger.info(
            "Cleanup job started — removing snapshots captured before %s",
            cutoff_time.isoformat(),
        )

        # Query các violations có ảnh chưa bị xóa và đã quá 24h
        expired_violations = (
            db.query(Violation)
            .filter(
                Violation.captured_at < cutoff_time,
                Violation.image_path.isnot(None),
            )
            .all()
        )

        if not expired_violations:
            logger.info("Cleanup job: No expired snapshots found.")
            return

        logger.info("Found %d expired snapshot(s) to clean up.", len(expired_violations))

        touched_dirs = set()

        for violation in expired_violations:
            try:
                # Xóa file ảnh trên disk
                if violation.image_path and os.path.isfile(violation.image_path):
                    touched_dirs.add(os.path.dirname(violation.image_path))
                    os.remove(violation.image_path)
                    logger.debug(
                        "Deleted snapshot file: %s (violation_id=%d)",
                        violation.image_path,
                        violation.id,
                    )

                # Cập nhật DB: giữ metadata, xóa đường dẫn ảnh
                violation.image_path = None
                deleted_count += 1

            except OSError as file_err:
                logger.warning(
                    "Failed to delete file %s for violation_id=%d: %s",
                    violation.image_path,
                    violation.id,
                    file_err,
                )
                # Vẫn set image_path = None nếu file không tồn tại
                violation.image_path = None
                error_count += 1

            except Exception as exc:
                logger.error(
                    "Unexpected error processing violation_id=%d: %s",
                    violation.id,
                    exc,
                    exc_info=True,
                )
                error_count += 1

        # Commit tất cả thay đổi
        db.commit()

        # Dọn dẹp các thư mục riêng-theo-sinh-viên đã trở nên rỗng sau khi xóa hết ảnh
        # (tránh để lại hàng trăm folder rỗng trong snapshots/ theo thời gian dài chạy)
        removed_dirs = 0
        for dir_path in touched_dirs:
            try:
                if os.path.isdir(dir_path) and not os.listdir(dir_path):
                    os.rmdir(dir_path)
                    removed_dirs += 1
            except OSError:
                pass  # Không sao nếu chưa xóa được — lần cleanup sau sẽ thử lại

        logger.info(
            "Cleanup job completed — Deleted: %d, Errors: %d, Empty folders removed: %d",
            deleted_count,
            error_count,
            removed_dirs,
        )

    except Exception as exc:
        logger.error("Cleanup job failed critically: %s", exc, exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass

    finally:
        try:
            db.close()
        except Exception:
            pass


# ──────────────────────────────────────────────────────────
# Scheduler Management
# ──────────────────────────────────────────────────────────

_scheduler: BackgroundScheduler | None = None


def start_scheduler():
    """
    Khởi động APScheduler với job cleanup chạy mỗi giờ.
    Gọi hàm này trong FastAPI startup event.
    """
    global _scheduler

    try:
        _scheduler = BackgroundScheduler(
            job_defaults={
                "coalesce": True,         # Gộp các lần chạy bị bỏ lỡ
                "max_instances": 1,        # Chỉ 1 instance chạy đồng thời
                "misfire_grace_time": 300,  # Cho phép trễ 5 phút
            }
        )

        _scheduler.add_job(
            func=cleanup_expired_snapshots,
            trigger=IntervalTrigger(hours=CLEANUP_INTERVAL_HOURS),
            id="cleanup_expired_snapshots",
            name="Auto-cleanup expired snapshot images",
            replace_existing=True,
        )

        _scheduler.add_job(
            func=backup_database,
            trigger=IntervalTrigger(hours=BACKUP_INTERVAL_HOURS),
            id="backup_database",
            name="Sao lưu cơ sở dữ liệu",
            replace_existing=True,
        )

        _scheduler.start()
        logger.info(
            "APScheduler started — cleanup job runs every %d hour(s), "
            "retention period: %d hours",
            CLEANUP_INTERVAL_HOURS,
            IMAGE_RETENTION_HOURS,
        )
        logger.info("Job sao lưu cơ sở dữ liệu chạy mỗi %d giờ.", BACKUP_INTERVAL_HOURS)

    except Exception as exc:
        logger.error("Failed to start APScheduler: %s", exc, exc_info=True)
        raise


def shutdown_scheduler():
    """
    Tắt APScheduler gracefully.
    Gọi hàm này trong FastAPI shutdown event.
    """
    global _scheduler

    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=True)
            logger.info("APScheduler shut down gracefully.")
        except Exception as exc:
            logger.warning("Error shutting down APScheduler: %s", exc)
        finally:
            _scheduler = None
