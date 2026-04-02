"""Migrate legacy rollback tables to generic bot_* tables.

Usage (Toolforge/local with DB credentials configured as usual):
    python scripts/migrate_db.py
"""

from __future__ import annotations

from toolsdb import get_conn


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute("SHOW TABLES LIKE %s", (table_name,))
    return cursor.fetchone() is not None


def _column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(f"SHOW COLUMNS FROM {table_name} LIKE %s", (column_name,))
    return cursor.fetchone() is not None


def migrate() -> None:
    with get_conn() as conn:
        with conn.cursor() as cursor:
            if _table_exists(cursor, "rollback_jobs") and not _table_exists(
                cursor, "bot_jobs"
            ):
                cursor.execute("RENAME TABLE rollback_jobs TO bot_jobs")

            if _table_exists(cursor, "rollback_job_items") and not _table_exists(
                cursor, "bot_job_items"
            ):
                cursor.execute("RENAME TABLE rollback_job_items TO bot_job_items")

            if _table_exists(cursor, "bot_jobs") and not _column_exists(
                cursor, "bot_jobs", "job_type"
            ):
                cursor.execute("ALTER TABLE bot_jobs ADD COLUMN job_type VARCHAR(32) NULL")

        conn.commit()


if __name__ == "__main__":
    migrate()
    print("Database migration completed.")
