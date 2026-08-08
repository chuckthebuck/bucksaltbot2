"""Database schema owned by Chuck the File Changer.

The framework supplies the connection, but this module owns its queue tables.
Keeping the bootstrap here means a newly installed module cannot enqueue work
against tables that only happen to exist in a particular framework checkout.
"""

from __future__ import annotations


def ensure_queue_tables(conn) -> None:
    """Create the module queue tables if this deployment does not have them."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chuck_file_change_jobs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                batch_id BIGINT NOT NULL,
                requested_by VARCHAR(255) NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'queued',
                dry_run TINYINT(1) NOT NULL DEFAULT 1,
                apply_requested TINYINT(1) NOT NULL DEFAULT 0,
                source_url VARCHAR(1024) NULL,
                payload_json LONGTEXT NOT NULL,
                result_json LONGTEXT NULL,
                error TEXT NULL,
                total_items INT NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_cfc_batch (batch_id),
                INDEX idx_cfc_status_created (status, created_at),
                INDEX idx_cfc_requested_created (requested_by, created_at)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chuck_file_change_job_items (
                id INT AUTO_INCREMENT PRIMARY KEY,
                job_id INT NOT NULL,
                page_title VARCHAR(512) NOT NULL,
                target_user VARCHAR(255) NULL,
                summary_hint TEXT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'queued',
                attempts INT NOT NULL DEFAULT 0,
                changed TINYINT(1) NOT NULL DEFAULT 0,
                diff LONGTEXT NULL,
                error TEXT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_cfc_job_id (job_id),
                INDEX idx_cfc_item_status (status)
            )
            """
        )
