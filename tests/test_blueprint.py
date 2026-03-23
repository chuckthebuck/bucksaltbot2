"""Tests for blueprint.py – Vite manifest loading and asset URL resolution."""

import blueprint as bp


def test_prod_asset_resolves_from_manifest(monkeypatch):
    """prod_asset returns the hashed path when the manifest has an entry."""
    monkeypatch.setattr(
        bp, "manifest", {"src/main.js": {"file": "assets/main.abc123.js"}}
    )
    monkeypatch.setattr(bp, "is_production", True)
    ctx = bp.add_context()
    assert ctx["asset"]("src/main.js") == "/assets/assets/main.abc123.js"


def test_prod_asset_falls_back_when_entry_missing(monkeypatch):
    """prod_asset falls back to /assets/{file} when the file is not in the manifest."""
    monkeypatch.setattr(bp, "manifest", {})
    monkeypatch.setattr(bp, "is_production", True)
    ctx = bp.add_context()
    assert ctx["asset"]("src/unknown.js") == "/assets/src/unknown.js"


def test_prod_asset_falls_back_when_manifest_entry_has_no_file_key(monkeypatch):
    """prod_asset falls back when the manifest entry lacks a 'file' key."""
    monkeypatch.setattr(bp, "manifest", {"src/main.js": {"name": "main"}})
    monkeypatch.setattr(bp, "is_production", True)
    ctx = bp.add_context()
    assert ctx["asset"]("src/main.js") == "/assets/src/main.js"


def test_dev_asset_returns_vite_origin_url(monkeypatch):
    """dev_asset prefixes the Vite dev-server origin."""
    monkeypatch.setattr(bp, "is_production", False)
    monkeypatch.setattr(bp, "VITE_ORIGIN", "http://localhost:5173")
    ctx = bp.add_context()
    assert ctx["asset"]("src/main.js") == "http://localhost:5173/assets/src/main.js"


def test_is_production_exposed_in_context(monkeypatch):
    """add_context always exposes is_production."""
    monkeypatch.setattr(bp, "is_production", True)
    ctx = bp.add_context()
    assert ctx["is_production"] is True


def test_manifest_empty_when_file_missing(monkeypatch):
    """blueprint stays usable when manifest.json is absent (manifest == {})."""
    monkeypatch.setattr(bp, "manifest", {})
    ctx = bp.add_context()
    assert callable(ctx["asset"])
    # Any unknown file should not raise and should return a valid path.
    result = ctx["asset"]("not_there.js")
    assert result.startswith("/assets/")
