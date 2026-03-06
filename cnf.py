import configparser as cfp
import os

CNF_PATH = "/etc/mysql/conf.d/replica.my.cnf"

cnf = cfp.ConfigParser()
cnf.read(CNF_PATH)

if cnf.has_section("client"):
    user = cnf["client"].get("user")
    password = cnf["client"].get("password")
    host = "tools.db.svc.wikimedia.cloud"
else:
    user = os.getenv("TOOL_TOOLSDB_USER")
    password = os.getenv("TOOL_TOOLSDB_PASSWORD")
    host = "localhost"

config = {
    "host": host,
    "user": user,
    "password": password,
}
