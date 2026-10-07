"""Module-owned SQL schema for audit history and durable queue state."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def init_schema(connection_factory: Callable[[], Any] | None = None) -> None:
    """Create every Self Delete table without changing framework-owned schema."""
    if connection_factory is None:
        from toolsdb import get_conn

        connection_factory = get_conn

    with connection_factory() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS self_delete_runs (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    framework_run_id BIGINT NULL,
                    category_title VARCHAR(512) NOT NULL,
                    dry_run TINYINT(1) NOT NULL DEFAULT 1,
                    max_age_seconds INT NOT NULL,
                    worker_count INT NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'running',
                    discovered_count INT NOT NULL DEFAULT 0,
                    eligible_count INT NOT NULL DEFAULT 0,
                    deleted_count INT NOT NULL DEFAULT 0,
                    skipped_count INT NOT NULL DEFAULT 0,
                    failed_count INT NOT NULL DEFAULT 0,
                    config_json LONGTEXT NULL,
                    error TEXT NULL,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    finished_at TIMESTAMP NULL,
                    INDEX idx_self_delete_runs_status_started (status, started_at),
                    INDEX idx_self_delete_runs_framework_run (framework_run_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS self_delete_candidates (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    run_id BIGINT NOT NULL,
                    page_id BIGINT NULL,
                    file_title VARCHAR(512) NOT NULL,
                    uploader VARCHAR(255) NULL,
                    requester VARCHAR(255) NULL,
                    upload_timestamp VARCHAR(32) NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'discovered',
                    reason_code VARCHAR(64) NULL,
                    reason_detail TEXT NULL,
                    checks_json LONGTEXT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    UNIQUE KEY uq_self_delete_run_title (run_id, file_title),
                    INDEX idx_self_delete_candidate_status (run_id, status)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS self_delete_events (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    run_id BIGINT NOT NULL,
                    candidate_id BIGINT NULL,
                    level VARCHAR(16) NOT NULL,
                    event_type VARCHAR(64) NOT NULL,
                    message TEXT NOT NULL,
                    context_json LONGTEXT NULL,
                    worker_name VARCHAR(128) NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_self_delete_events_run (run_id, id),
                    INDEX idx_self_delete_events_candidate (candidate_id, id),
                    INDEX idx_self_delete_events_type (event_type)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS self_delete_jobs (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    audit_run_id BIGINT NOT NULL,
                    batch_id BIGINT NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'queued',
                    dry_run TINYINT(1) NOT NULL DEFAULT 1,
                    total_items INT NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_self_delete_jobs_batch (batch_id),
                    INDEX idx_self_delete_jobs_status (status, created_at)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS self_delete_job_items (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    job_id BIGINT NOT NULL,
                    audit_candidate_id BIGINT NOT NULL,
                    page_id BIGINT NULL,
                    file_title VARCHAR(512) NOT NULL,
                    target_user VARCHAR(255) NULL,
                    payload_json LONGTEXT NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'queued',
                    attempts INT NOT NULL DEFAULT 0,
                    error TEXT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    INDEX idx_self_delete_items_job (job_id),
                    INDEX idx_self_delete_items_status (status, id)
                )
                """
            )
        conn.commit()
