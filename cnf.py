import configparser as cfp
import os

CNF_PATH = os.path.expanduser("~/replica.my.cnf")


def load_cnf():
    cnf = cfp.ConfigParser()
    if os.path.exists(CNF_PATH):
        cnf.read(CNF_PATH)
    return cnf


cnf = load_cnf()

if cnf.has_section("client"):
    user = cnf.get("client", "user")
    password = cnf.get("client", "password")
else:
    user = os.environ.get("TOOL_TOOLSDB_USER")
    password = os.environ.get("TOOL_TOOLSDB_PASSWORD")

config = {
    "host": "tools-db",
    "user": user,
    "password": password,
}
