import pymysql as sql

from cnf import config



    

   def get_conn():
    init_db()
    return sql.connect(
        user=config['user'],
        password=config['password'],
        host=config['host'],
        database=f'{config["user"]}__match_and_split',
    )
    return dbconn
