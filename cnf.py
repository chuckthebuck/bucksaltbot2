import configparser as cfp
import os

CNF_PATH = os.path.expanduser("~/replica.my.cnf")
TOOLFORGE_DEFAULT_HOST = "tools-db"
LOCAL_DEFAULT_HOST = "127.0.0.1"


def load_cnf():
    cnf = cfp.ConfigParser()
    if os.path.exists(CNF_PATH):
        cnf.read(CNF_PATH)
    return cnf


cnf = load_cnf()

if cnf.has_section("client"):
    user = cnf.get("client", "user")
    password = cnf.get("client", "password")
    host = os.environ.get("TOOL_TOOLSDB_HOST", TOOLFORGE_DEFAULT_HOST)
else:
    user = os.environ.get("TOOL_TOOLSDB_USER")
    password = os.environ.get("TOOL_TOOLSDB_PASSWORD")
    host = os.environ.get("TOOL_TOOLSDB_HOST", LOCAL_DEFAULT_HOST)

config = {
    "host": host,
    "user": user,
    "password": password,
    "database": os.environ.get("TOOL_TOOLSDB_DATABASE"),
}
