"""Create idempotent nomination replies and credited-user talk notifications.

Approved and hard-failed reviews notify each credited user; manual-review results
leave the nomination in place and append an explanatory note.  Hidden markers
make repeated scheduled runs safe, while the wiki adapter keeps the same message
generation path for dry-run previews and live publication.
"""

from __future__ import annotations

from .config import BOT_MARKER_PREFIX, ENABLE_REPLIES, ENABLE_TALK_NOTICES, FOUR_PAGE
from .models import FourAwardNomination, NominationResult
from .wiki import get_wiki


def _marker(nomination: FourAwardNomination, status: str) -> str:
    """Build the article/status marker used to suppress duplicate messages."""
    return f"<!-- {BOT_MARKER_PREFIX}:{status}:{nomination.article.replace(' ', '_')} -->"


def _issue_text(result: NominationResult) -> str:
    """Join structured review issues into compact message-ready prose."""
    return "; ".join(issue.reason for issue in result.issues) if result.issues else "No additional details were provided."


def _notify_user(user: str, article: str, result: NominationResult) -> None:
    """Append one approved/failed notice to a credited user's talk page.

    The marker check is scoped to that user's page, so every credited user gets a
    notice while reruns do not duplicate it.
    """
    if not ENABLE_TALK_NOTICES:
        return
    wiki = get_wiki()
    title = f"User talk:{user}"
    text = wiki.get_text(title)
    marker = _marker(result.nomination, result.status)
    if marker in text:
        return
    if result.status == "approved":
        message = f"== Four Award ==\n{marker}\n{{{{subst:Four Award Message|{article}}}}}\n"
        summary = f"Notify {user} of Four Award for [[{article}]]"
    else:
        message = (
            f"== Four Award ==\n{marker}\n"
            f"The Four Award nomination for [[{article}]] was not successful: {_issue_text(result)} "
            "You are welcome to renominate once the concern has been addressed. ~~~~\n"
        )
        summary = f"Notify {user} of unsuccessful Four Award nomination for [[{article}]]"
    wiki.save_text(title, f"{text.rstrip()}\n\n{message}", summary)


def _reply_on_nomination(nomination: FourAwardNomination, result: NominationResult) -> None:
    """Append one manual-review note only while the source block still exists."""
    wiki = get_wiki()
    text = wiki.get_text(FOUR_PAGE)
    marker = _marker(nomination, result.status)
    # A concurrent page edit may have removed the nomination after parsing.  Do
    # not recreate it merely to attach a note.
    if marker in text or nomination.raw_text not in text:
        return
    body = f"\n: {marker} '''FourAwardHelper note:''' Manual review is needed. {_issue_text(result)} ~~~~\n"
    new_text = text.replace(nomination.raw_text, nomination.raw_text + body, 1)
    wiki.save_text(FOUR_PAGE, new_text, f"Reply to Four Award nomination for [[{nomination.article}]]")


def reply_result(nomination: FourAwardNomination, result: NominationResult) -> None:
    """Route terminal results to talk pages and manual results to the source page."""
    if not ENABLE_REPLIES:
        return
    if result.status in {"approved", "failed_to_verify"}:
        for user in nomination.users:
            _notify_user(user, nomination.article, result)
    else:
        _reply_on_nomination(nomination, result)
