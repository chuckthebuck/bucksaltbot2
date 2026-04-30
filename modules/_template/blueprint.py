"""Template module blueprint.

Replace this with your module's business logic and routes.
"""

from flask import Blueprint, render_template_string, session, abort, jsonify

blueprint = Blueprint("template_module", __name__)


@blueprint.route("/")
def index():
    """Module landing page."""
    username = session.get("username")
    if not username:
        abort(401)
    
    return render_template_string("""
        <div style="padding: 20px; font-family: sans-serif;">
            <h1>Template Module</h1>
            <p>Welcome, <strong>{{ username }}</strong>!</p>
            <p>Replace this template with your module's UI.</p>
            <hr>
            <h2>Available Endpoints</h2>
            <ul>
                <li><a href="/">/</a> — This page</li>
                <li><a href="/api/v1/template_module/status">/api/v1/template_module/status</a> — Health check</li>
            </ul>
        </div>
    """, username=username)


@blueprint.route("/api/v1/template_module/status")
def status():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "module": "template_module",
    })
