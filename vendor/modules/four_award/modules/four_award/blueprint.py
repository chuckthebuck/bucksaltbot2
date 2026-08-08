from flask import Blueprint
from .service import run_four_award_sync

blueprint = Blueprint("four_award", __name__)

@blueprint.route("/api/v1/four_award/cron/run")
def cron_run():
    return run_four_award_sync()
