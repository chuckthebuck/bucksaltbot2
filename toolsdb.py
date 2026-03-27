import pymysql as sql

from cnf import config


def _ensure_column(
    cursor, table_name: str, column_name: str, ddl_fragment: str
) -> None:
    """Add a missing column with ``ALTER TABLE`` in an idempotent way."""
    cursor.execute(f"SHOW COLUMNS FROM {table_name} LIKE %s", (column_name,))
    if cursor.fetchone():
        return
    cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {ddl_fragment}")


def _db_user() -> str:
    return config.get("user") or config.get("username")


def _db_name() -> str:
    return f"{_db_user()}__match_and_split"


def _connect(database=None):
    return sql.connections.Connection(
        user=_db_user(),
        password=config["password"],
        host=config["host"],
        database=database,
    )


def init_db():
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {_db_name()}")
            cursor.execute(f"USE {_db_name()}")

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS rollback_jobs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    requested_by VARCHAR(255) NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    dry_run TINYINT(1) NOT NULL DEFAULT 0,
                    batch_id BIGINT NULL,
                    request_type VARCHAR(32) NULL,
                    requested_endpoint VARCHAR(32) NULL,
                    approved_endpoint VARCHAR(32) NULL,
                    approval_required VARCHAR(32) NULL,
                    approved_by VARCHAR(255) NULL,
                    approved_at TIMESTAMP NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # Ensure approval columns exist for legacy deployments where
            # rollback_jobs was created before request/approval workflows.
            _ensure_column(
                cursor, "rollback_jobs", "request_type", "request_type VARCHAR(32) NULL"
            )
            _ensure_column(
                cursor,
                "rollback_jobs",
                "requested_endpoint",
                "requested_endpoint VARCHAR(32) NULL",
            )
            _ensure_column(
                cursor,
                "rollback_jobs",
                "approved_endpoint",
                "approved_endpoint VARCHAR(32) NULL",
            )
            _ensure_column(
                cursor,
                "rollback_jobs",
                "approval_required",
                "approval_required VARCHAR(32) NULL",
            )
            _ensure_column(
                cursor, "rollback_jobs", "approved_by", "approved_by VARCHAR(255) NULL"
            )
            _ensure_column(
                cursor, "rollback_jobs", "approved_at", "approved_at TIMESTAMP NULL"
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS rollback_job_items (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    job_id INT NOT NULL,
                    file_title VARCHAR(512) NOT NULL,
                    target_user VARCHAR(255) NOT NULL,
                    summary TEXT NULL,
                    status VARCHAR(32) NOT NULL,
                    error TEXT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_job_id (job_id)
                )
                """
            )

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_config (
                    config_key VARCHAR(128) PRIMARY KEY,
                    config_value TEXT NOT NULL,
                    updated_by VARCHAR(255) NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP
                )
                """
            )

        conn.commit()
    finally:
        conn.close()


def get_conn():
    init_db()
    return _connect(database=_db_name())


def get_runtime_config(keys=None):
    """Return runtime config values as {config_key: config_value}.

    Values are stored as strings and interpreted by the caller.
    """
    with get_conn() as conn:
        with conn.cursor() as cursor:
            if keys:
                placeholders = ",".join(["%s"] * len(keys))
                cursor.execute(
                    f"""
                    SELECT config_key, config_value
                    FROM runtime_config
                    WHERE config_key IN ({placeholders})
                    """,
                    tuple(keys),
                )
            else:
                cursor.execute(
                    """
                    SELECT config_key, config_value
                    FROM runtime_config
                    """
                )

            rows = cursor.fetchall()

    return {row[0]: row[1] for row in rows}


def upsert_runtime_config(values, updated_by=None):
    """Insert or update runtime config values.

    values should be a mapping of config_key -> string config_value.
    """
    if not values:
        return

    with get_conn() as conn:
        with conn.cursor() as cursor:
            for key, value in values.items():
                cursor.execute(
                    """
                    INSERT INTO runtime_config (config_key, config_value, updated_by)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        config_value = VALUES(config_value),
                        updated_by = VALUES(updated_by),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (key, str(value), updated_by),
                )
        conn.commit()
