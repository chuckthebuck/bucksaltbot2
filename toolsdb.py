import pymysql as sql

from cnf import config


def init_db():
    initdbconn = sql.connections.Connection(user=config['user'], password=config['password'], host=config['host'])
    with initdbconn.cursor() as cursor:
        cursor.execute(f'CREATE DATABASE IF NOT EXISTS {config["user"]}__match_and_split;')
        cursor.execute(f'USE {config["user"]}__match_and_split;')
        cursor.execute('''CREATE TABLE IF NOT EXISTS `rollback_jobs` (
            `id` INT NOT NULL AUTO_INCREMENT,
            `requested_by` VARCHAR(255) NOT NULL,
            `status` VARCHAR(255) NOT NULL,
            `dry_run` TINYINT(1) NOT NULL DEFAULT 0,
            `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (`id`)
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS `rollback_job_items` (
            `id` INT NOT NULL AUTO_INCREMENT,
            `job_id` INT NOT NULL,
            `file_title` VARCHAR(300) NOT NULL,
            `target_user` VARCHAR(255) NOT NULL,
            `summary` VARCHAR(500),
            `status` VARCHAR(255) NOT NULL DEFAULT 'queued',
            `error` TEXT,
            `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (`id`),
            INDEX (`job_id`)
        )''')
        # Graceful migration: add batch_id column to rollback_jobs if it doesn't exist yet.
        # batch_id groups job chunks that belong to the same large batch submission.
        try:
            cursor.execute(
                'ALTER TABLE `rollback_jobs` ADD COLUMN `batch_id` BIGINT NULL'
            )
        except sql.err.OperationalError as e:
            if e.args[0] == 1060:  # Duplicate column name – already migrated, safe to ignore
                pass
            else:
                import logging
                logging.getLogger(__name__).error(
                    "Unexpected error during batch_id migration: %s", e
                )
                raise
    initdbconn.commit()
    initdbconn.close()


def get_conn():
    init_db()
    dbconn = sql.connections.Connection(
        user=config['user'],
        password=config['password'],
        host=config['host'],
        database=f'{config["user"]}__match_and_split',
    )
    return dbconn
