"""Legacy synchronous Four Award trigger retained for compatibility.

Because this Blueprint has no prefix, the framework mounts it below
``/four_award``. Its resulting ``GET /four_award/api/v1/four_award/cron/run``
route has no authentication or cron token and bypasses framework run tracking
and runtime-config injection. Production scheduling uses the manifest handler;
new integrations must not use this endpoint.
"""

from flask import Blueprint
from .service import run_four_award_sync

blueprint = Blueprint("four_award", __name__)

@blueprint.route("/api/v1/four_award/cron/run")
def cron_run():
    """Synchronously run the unsupported, untracked compatibility path."""
    return run_four_award_sync()
