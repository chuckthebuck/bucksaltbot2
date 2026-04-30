from __future__ import annotations

from typing import Any

from framework.action import BotAction


class RollbackAction(BotAction):
    def execute_item(
        self,
        item_key: str,
        item_target: str,
        summary: str | None,
        requested_by: str,
        site: Any,
        dry_run: bool,
    ) -> None:
        if dry_run:
            return

        token = site.tokens["rollback"]
        requester_tag = f"requested-by={requested_by}"
        base = (summary or "").strip()

        if not base:
            final_summary = f"Mass rollback via bucksaltbot queue; {requester_tag}"
        elif requester_tag in base:
            final_summary = base
        else:
            final_summary = f"{base}; {requester_tag}"

        site.simple_request(
            action="rollback",
            title=item_key,
            user=item_target,
            token=token,
            summary=final_summary,
            markbot=True,
            bot=True,
        ).submit()
