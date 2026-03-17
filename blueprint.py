import json
import os
from pathlib import Path
from flask import Blueprint

# Get environment variables.
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "0")
VITE_ORIGIN = os.getenv("VITE_ORIGIN", "http://localhost:5173")

# Set application constants.
is_production = FLASK_DEBUG != "1"
project_path = Path(os.path.dirname(os.path.abspath(__file__)))

# Create a blueprint that stores all Vite-related functionality.
assets_blueprint = Blueprint(
    "assets_blueprint",
    __name__,
    static_folder="assets_compiled/bundled",
    static_url_path="/assets/bundled",
)

# Load manifest file in the production environment.
def load_manifest():
    manifest_path = project_path / "assets_compiled/manifest.json"
    try:
        with open(manifest_path, "r") as content:
            return json.load(content)
    except OSError:
        return {}


# Add `asset()` function and `is_production` to app context.
@assets_blueprint.app_context_processor
def add_context():
    def dev_asset(file_path):
        return f"{VITE_ORIGIN}/assets/{file_path}"

    def prod_asset(file_path):
        manifest = load_manifest()  

        asset_meta = manifest.get(file_path)
        if asset_meta and asset_meta.get('file'):
            return f"/assets/{asset_meta['file']}"

        return f"/assets/{file_path}"

    return {
        "asset": prod_asset if is_production else dev_asset,
        "is_production": is_production,
    }
