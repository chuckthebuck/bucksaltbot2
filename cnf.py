import configparser as cfp
import os

CNF_PATH = os.path.expanduser("~/replica.my.cnf")


def load_cnf():
    cnf = cfp.ConfigParser()
    if os.path.exists(CNF_PATH):
        cnf.read(CNF_PATH)
    return cnf


cnf = load_cnf()

if "client" in cnf:
    # Toolforge replica config
    user = cnf["client"]["user"]
    password = cnf["client"]["password"]
    remote = "tools-db"

else:
    # fallback for local/dev
    user = os.environ.get("TOOL_TOOLSDB_USER")
    password = os.environ.get("TOOL_TOOLSDB_PASSWORD")
    remote = "localhost"

if os.environ.get("DOCKER"):
    remote = "mariadb"


config = {
    "host": remote,
    "user": user,
    "password": password,
}
