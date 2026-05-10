from __future__ import annotations

from .config import BOT_MARKER_PREFIX, ENABLE_REPLIES, ENABLE_TALK_NOTICES, FOUR_PAGE
from .models import FourAwardNomination, NominationResult
from .wiki import get_wiki


def _marker(nomination: FourAwardNomination, status: str) -> str:
    return f"<!-- {BOT_MARKER_PREFIX}:{status}:{nomination.article.replace(' ', '_')} -->"


def _issue_text(result: NominationResult) -> str:
    return "; ".join(issue.reason for issue in result.issues) if result.issues else "No additional details were provided."


def _notify_user(user: str, article: str, result: NominationResult) -> None:
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
    wiki = get_wiki()
    text = wiki.get_text(FOUR_PAGE)
    marker = _marker(nomination, result.status)
    if marker in text or nomination.raw_text not in text:
        return
    body = f"\n: {marker} '''FourAwardHelper note:''' Manual review is needed. {_issue_text(result)} ~~~~\n"
    new_text = text.replace(nomination.raw_text, nomination.raw_text + body, 1)
    wiki.save_text(FOUR_PAGE, new_text, f"Reply to Four Award nomination for [[{nomination.article}]]")


def reply_result(nomination: FourAwardNomination, result: NominationResult) -> None:
    if not ENABLE_REPLIES:
        return
    if result.status in {"approved", "failed_to_verify"}:
        for user in nomination.users:
            _notify_user(user, nomination.article, result)
    else:
        _reply_on_nomination(nomination, result)
