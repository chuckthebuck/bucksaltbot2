import configparser
import os

CNF_PATH = os.path.join(os.environ["HOME"], "replica.my.cnf")

cnf = configparser.ConfigParser()
cnf.read(CNF_PATH)

user = cnf["client"]["user"]
password = cnf["client"]["password"]

config = {
    "host": "tools-db",
    "user": user,
    "password": password,
}
