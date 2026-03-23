import pymysql as sql

from cnf import config


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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
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

        conn.commit()
    finally:
        conn.close()


def get_conn():
    init_db()
    return _connect(database=_db_name())
