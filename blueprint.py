import json
import os
from pathlib import Path
from flask import Blueprint
from functools import lru_cache

FLASK_DEBUG = os.getenv("FLASK_DEBUG", "0")
VITE_ORIGIN = os.getenv("VITE_ORIGIN", "http://localhost:5173")

is_production = FLASK_DEBUG != "1"
project_path = Path(__file__).parent

# ✅ REMOVE static_folder config
assets_blueprint = Blueprint(
    "assets_blueprint",
    __name__,
)


# ✅ FIXED manifest path
@lru_cache()
def load_manifest():
    manifest_path = project_path / "static/dist/.vite/manifest.json"
    try:
        with open(manifest_path, "r") as f:
            return json.load(f)
    except OSError:
        return {}


manifest = load_manifest()


# ✅ Context helpers
@assets_blueprint.app_context_processor
def add_context():

    def dev_asset(file_path):
        return f"{VITE_ORIGIN}/{file_path}"

    def prod_asset(file_path):
        entry = manifest.get(file_path)

        if entry and entry.get("file"):
            return f"/static/dist/{entry['file']}"

        return f"/static/dist/{file_path}"

    def prod_css(file_path):
        entry = manifest.get(file_path)

        if entry and entry.get("css"):
            return [f"/static/dist/{css}" for css in entry["css"]]

        return []

    return {
        "asset": prod_asset if is_production else dev_asset,
        "asset_css": prod_css if is_production else (lambda x: []),
        "is_production": is_production,
    }
