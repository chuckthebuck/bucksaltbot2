import pymysql as sql

from cnf import config


def init_db():
    initdbconn = sql.connections.Connection(user=config['username'], password=config['password'], host=config['host'])
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
    initdbconn.close()


def get_conn():
    init_db()
    dbconn = sql.connections.Connection(
        user=config['username'],
        password=config['password'],
        host=config['host'],
        database=f'{config["username"]}__match_and_split',
    )
    return dbconn
