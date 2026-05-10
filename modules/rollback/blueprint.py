"""Bundled rollback module blueprint.

This module is the migration example for the framework: a UI-facing module
that reuses the framework's shared rollback routes while presenting a module
landing page under /rollback/.
"""

from __future__ import annotations

from flask import Blueprint, abort, redirect, render_template_string, session

from app import is_maintainer
from router.module_registry import get_module_definition, user_has_module_access

blueprint = Blueprint("rollback_module", __name__)


_ROLLBACK_PAGES = [
    ("Rollback queue", "/rollback-queue"),
    ("From diff", "/rollback-from-diff"),
    ("By account", "/rollback-account"),
    ("Batch rollback", "/rollback_batch"),
    ("Request review", "/rollback-requests"),
    ("Runtime config", "/rollback-config"),
]


def _require_module_access() -> str:
    username = session.get("username")
    if not username:
        abort(401)

    if not user_has_module_access(
        "rollback",
        username,
        is_maintainer=is_maintainer(username),
    ):
        abort(403)

    return username


def _rollback_definition():
    record = get_module_definition("rollback")
    if record is None:
        abort(404)
    return record.definition


@blueprint.route("/")
def index():
    username = _require_module_access()
    definition = _rollback_definition()

    return render_template_string(
        """
        <div class="module-shell">
          <h1>{{ title }}</h1>
          <p>Module: {{ module_name }}</p>
          <p>Signed in as {{ username }}</p>
          <p>This module wraps the rollback workflow as a standalone example.</p>
          <h2>Pages</h2>
          <ul>
            {% for label, href in pages %}
              <li><a href="{{ href }}">{{ label }}</a></li>
            {% endfor %}
          </ul>
          <h2>Buildpacks</h2>
          <p>{{ buildpacks|join(", ") if buildpacks else "framework default" }}</p>
        </div>
        """,
        title=definition.title or "Rollback",
        module_name=definition.name,
        username=username,
        pages=_ROLLBACK_PAGES,
        buildpacks=definition.buildpacks,
    )


@blueprint.route("/queue")
def queue():
    _require_module_access()
    return redirect("/rollback-queue")


@blueprint.route("/from-diff")
def from_diff():
    _require_module_access()
    return redirect("/rollback-from-diff")


@blueprint.route("/account")
def account():
    _require_module_access()
    return redirect("/rollback-account")


@blueprint.route("/batch")
def batch():
    _require_module_access()
    return redirect("/rollback_batch")


@blueprint.route("/requests")
def requests_page():
    _require_module_access()
    return redirect("/rollback-requests")


@blueprint.route("/config")
def config_page():
    _require_module_access()
    return redirect("/rollback-config")
