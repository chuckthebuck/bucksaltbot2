import configparser as cfp
import os
from pathlib import Path

TOOLFORGE_DEFAULT_HOST = "tools.db.svc.wikimedia.cloud"
LOCAL_DEFAULT_HOST = None


def load_cnf():
    cnf = cfp.ConfigParser()
    for path in _candidate_cnf_paths():
        if path.exists():
            cnf.read(path)
            break
    return cnf


def _candidate_cnf_paths() -> list[Path]:
    paths = [Path.home() / "replica.my.cnf"]
    tool_data_dir = os.environ.get("TOOL_DATA_DIR")
    if tool_data_dir:
        paths.append(Path(tool_data_dir) / "replica.my.cnf")
    return paths


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _running_on_toolforge() -> bool:
    if _truthy_env("CHUCKBOT_LOCAL_SAFE_MODE"):
        return False
    if os.environ.get("TOOLFORGE"):
        return True
    if os.environ.get("TOOL_TOOLSDB_USER") and os.environ.get("TOOL_TOOLSDB_PASSWORD"):
        return True
    home = str(Path.home())
    return home.startswith("/data/project/")


def _default_host() -> str:
    if _running_on_toolforge():
        return TOOLFORGE_DEFAULT_HOST
    return LOCAL_DEFAULT_HOST


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


cnf = load_cnf()

if cnf.has_section("client"):
    user = cnf.get("client", "user")
    password = cnf.get("client", "password")
    host = _env("TOOL_TOOLSDB_HOST") or TOOLFORGE_DEFAULT_HOST
else:
    user = _env("TOOL_TOOLSDB_USER")
    password = _env("TOOL_TOOLSDB_PASSWORD")
    host = _env("TOOL_TOOLSDB_HOST") or _default_host()

config = {
    "host": host,
    "user": user,
    "password": password,
    "database": _env("TOOL_TOOLSDB_DATABASE"),
}
