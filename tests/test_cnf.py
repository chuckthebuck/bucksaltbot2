"""Tests for Toolforge/local database configuration detection."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _load_real_cnf_module():
    module_name = "_real_cnf_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, ROOT / "cnf.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_toolforge_env_credentials_default_to_toolsdb_host(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TOOL_TOOLSDB_HOST", raising=False)
    monkeypatch.delenv("CHUCKBOT_LOCAL_SAFE_MODE", raising=False)
    monkeypatch.setenv("TOOL_TOOLSDB_USER", "s12345")
    monkeypatch.setenv("TOOL_TOOLSDB_PASSWORD", "secret")

    cnf = _load_real_cnf_module()

    assert cnf.config["host"] == "tools.db.svc.wikimedia.cloud"
    assert cnf.config["user"] == "s12345"


def test_local_safe_mode_defaults_to_localhost(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TOOL_TOOLSDB_HOST", raising=False)
    monkeypatch.setenv("CHUCKBOT_LOCAL_SAFE_MODE", "1")
    monkeypatch.setenv("TOOL_TOOLSDB_USER", "user")
    monkeypatch.setenv("TOOL_TOOLSDB_PASSWORD", "password")

    cnf = _load_real_cnf_module()

    assert cnf.config["host"] == "127.0.0.1"


def test_replica_cnf_uses_toolforge_host(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TOOL_TOOLSDB_HOST", raising=False)
    (tmp_path / "replica.my.cnf").write_text(
        "[client]\nuser=s54321\npassword=secret\n",
        encoding="utf-8",
    )

    cnf = _load_real_cnf_module()

    assert cnf.config["host"] == "tools.db.svc.wikimedia.cloud"
    assert cnf.config["user"] == "s54321"
