"""Tests for status_updater.py."""

import time
from unittest.mock import MagicMock, patch


def test_resolve_pywikibot_dir_falls_back_from_unwritable_home(monkeypatch):
    import pywikibot_env

    monkeypatch.delenv("PYWIKIBOT_DIR", raising=False)
    monkeypatch.setenv("HOME", "/data/project/buckbot")

    attempted: list[str] = []

    def fake_mkdir(path_obj, parents=False, exist_ok=False):
        attempted.append(str(path_obj))
        if str(path_obj).startswith("/data/project"):
            raise PermissionError("denied")

    with patch("pywikibot_env.Path.mkdir", new=fake_mkdir):
        resolved = pywikibot_env.resolve_pywikibot_dir()

    assert str(resolved) == "/workspace/.pywikibot"
    assert attempted[0] == "/data/project/buckbot/.pywikibot"


# ── is_large_job ──────────────────────────────────────────────────────────────


def test_is_large_job_returns_false_for_single_job():
    import status_updater

    assert status_updater.is_large_job(1) is False


def test_is_large_job_returns_true_for_multiple_jobs():
    import status_updater

    assert status_updater.is_large_job(2) is True
    assert status_updater.is_large_job(10) is True


# ── is_batch_already_notified / mark_batch_notified ───────────────────────────


def test_is_batch_already_notified_returns_false_when_key_missing():
    import status_updater

    mock_redis = MagicMock()
    mock_redis.exists.return_value = 0

    with patch.object(status_updater, "_redis", mock_redis):
        result = status_updater.is_batch_already_notified(9999)

    assert result is False
    mock_redis.exists.assert_called_once_with("rollback:notified_batch:9999")


def test_is_batch_already_notified_returns_true_when_key_exists():
    import status_updater

    mock_redis = MagicMock()
    mock_redis.exists.return_value = 1

    with patch.object(status_updater, "_redis", mock_redis):
        result = status_updater.is_batch_already_notified(9999)

    assert result is True


def test_mark_batch_notified_sets_redis_key_with_ttl():
    import status_updater

    mock_redis = MagicMock()

    with patch.object(status_updater, "_redis", mock_redis):
        status_updater.mark_batch_notified(9999)

    mock_redis.set.assert_called_once_with(
        "rollback:notified_batch:9999",
        "1",
        ex=status_updater._NOTIFIED_BATCH_TTL,
    )


def test_mark_batch_notified_swallows_redis_errors():
    import status_updater

    mock_redis = MagicMock()
    mock_redis.set.side_effect = RuntimeError("redis down")

    with patch.object(status_updater, "_redis", mock_redis):
        # Should not raise
        status_updater.mark_batch_notified(9999)


# ── get_notify_list ───────────────────────────────────────────────────────────


def test_get_notify_list_parses_user_links():
    import status_updater

    mock_page = MagicMock()
    mock_page.text = "* [[User:Alice]]\n* [[User:Bob]]\n* [[User:Charlie]]"
    mock_site = MagicMock()

    with patch("status_updater.pywikibot.Page", return_value=mock_page):
        users = status_updater.get_notify_list(mock_site)

    assert users == ["Alice", "Bob", "Charlie"]


def test_get_notify_list_ignores_non_user_links():
    import status_updater

    mock_page = MagicMock()
    mock_page.text = "* [[User:Alice]]\n* [[Commons:Rules]]\n* [[File:Test.jpg]]"
    mock_site = MagicMock()

    with patch("status_updater.pywikibot.Page", return_value=mock_page):
        users = status_updater.get_notify_list(mock_site)

    assert users == ["Alice"]


def test_get_notify_list_returns_empty_on_exception():
    import status_updater

    mock_site = MagicMock()

    with patch("status_updater.pywikibot.Page", side_effect=RuntimeError("network")):
        users = status_updater.get_notify_list(mock_site)

    assert users == []


# ── is_flagged_bot ────────────────────────────────────────────────────────────


def test_is_flagged_bot_returns_true_when_bot_in_groups():
    import status_updater

    mock_user = MagicMock()
    mock_user.groups.return_value = ["bot", "autopatrolled"]
    mock_site = MagicMock()

    with patch("status_updater.pywikibot.User", return_value=mock_user):
        result = status_updater.is_flagged_bot(mock_site, "SomeBot")

    assert result is True


def test_is_flagged_bot_returns_false_when_bot_not_in_groups():
    import status_updater

    mock_user = MagicMock()
    mock_user.groups.return_value = ["autopatrolled", "confirmed"]
    mock_site = MagicMock()

    with patch("status_updater.pywikibot.User", return_value=mock_user):
        result = status_updater.is_flagged_bot(mock_site, "RegularUser")

    assert result is False


def test_is_flagged_bot_returns_false_on_exception():
    import status_updater

    mock_site = MagicMock()

    with patch("status_updater.pywikibot.User", side_effect=RuntimeError("oops")):
        result = status_updater.is_flagged_bot(mock_site, "SomeUser")

    assert result is False


# ── update_wiki_status ────────────────────────────────────────────────────────


def test_update_wiki_status_noop_when_not_live(monkeypatch):
    import status_updater

    monkeypatch.delenv("NOTDEV", raising=False)

    mock_site_cls = MagicMock()
    with patch("status_updater.pywikibot.Site", mock_site_cls):
        status_updater.update_wiki_status("Actively editing")

    mock_site_cls.assert_not_called()


def test_status_subpages_target_user_chuckbot_status_space_names():
    import status_updater

    assert status_updater.STATUS_PAGE == "User:Chuckbot/status"
    assert status_updater.STATUS_SUBPAGES["editing"] == "User:Chuckbot/status/editing"
    assert status_updater.STATUS_SUBPAGES["web"] == "User:Chuckbot/status/web"
    assert (
        status_updater.STATUS_SUBPAGES["last_edit"] == "User:Chuckbot/status/last edit"
    )
    assert (
        status_updater.STATUS_SUBPAGES["current_job"]
        == "User:Chuckbot/status/current job"
    )
    assert status_updater.STATUS_SUBPAGES["last_job"] == "User:Chuckbot/status/last job"
    assert status_updater.STATUS_SUBPAGES["details"] == "User:Chuckbot/status/details"
    assert status_updater.STATUS_SUBPAGES["warning"] == "User:Chuckbot/status/warning"
    assert status_updater.STATUS_SUBPAGES["updated"] == "User:Chuckbot/status/updated"


def test_update_wiki_status_saves_page_when_live(monkeypatch):
    import status_updater

    monkeypatch.setenv("NOTDEV", "1")

    mock_page = MagicMock()
    mock_site = MagicMock()

    with (
        patch("status_updater.pywikibot.Site", return_value=mock_site),
        patch("status_updater.pywikibot.Page", return_value=mock_page),
    ):
        status_updater.update_wiki_status(
            editing="Actively editing",
            current_job="Processing batch 12345 (job 1)",
            details="50 items queued",
        )

    # Should call save multiple times (once per status field)
    assert mock_page.save.call_count >= 7  # All fields except optional warning
    # Verify each call has the right parameters
    for call in mock_page.save.call_args_list:
        assert call.kwargs.get("minor") is True
        assert call.kwargs.get("bot") is True


def test_update_wiki_status_includes_warning_when_provided(monkeypatch):
    import status_updater

    monkeypatch.setenv("NOTDEV", "1")

    mock_site = MagicMock()
    page_texts = {}

    def capture_text(site, page_title):
        page = MagicMock()

        # Capture the text assigned to this page
        def save_text(*args, **kwargs):
            page_texts[page_title] = page.text

        page.save = save_text
        return page

    with (
        patch("status_updater.pywikibot.Site", return_value=mock_site),
        patch("status_updater.pywikibot.Page", side_effect=capture_text),
    ):
        status_updater.update_wiki_status(
            editing="Actively editing",
            warning="Large batch job in progress.",
        )

    # Check that warning subpage was written
    assert "Large batch job in progress." in page_texts.get(
        status_updater.STATUS_SUBPAGES["warning"], ""
    )


def test_update_wiki_status_omits_warning_field_when_none(monkeypatch):
    import status_updater

    monkeypatch.setenv("NOTDEV", "1")

    page_calls = []

    def track_page(site, page_title):
        page = MagicMock()
        page_calls.append(page_title)
        return page

    with (
        patch("status_updater.pywikibot.Site"),
        patch("status_updater.pywikibot.Page", side_effect=track_page),
    ):
        status_updater.update_wiki_status("Idle")

    # Warning page should be created and cleared (empty text)
    assert status_updater.STATUS_SUBPAGES["warning"] in page_calls


def test_update_wiki_status_swallows_exceptions(monkeypatch):
    import status_updater

    monkeypatch.setenv("NOTDEV", "1")

    with patch("status_updater.pywikibot.Site", side_effect=RuntimeError("oops")):
        # Should not raise
        status_updater.update_wiki_status("Idle")


def test_update_wiki_status_uses_provided_site_without_reauth(monkeypatch):
    import status_updater

    monkeypatch.setenv("NOTDEV", "1")

    mock_page = MagicMock()
    provided_site = MagicMock()

    with (
        patch("status_updater.pywikibot.Page", return_value=mock_page),
        patch("status_updater._get_authenticated_site") as mock_get_site,
    ):
        status_updater.update_wiki_status("Idle", site=provided_site)

    mock_get_site.assert_not_called()


def test_run_status_cron_update_preserves_job_fields(monkeypatch):
    import status_updater

    monkeypatch.setenv("NOTDEV", "1")

    written_keys = []

    def track_save(site, key, text):
        written_keys.append(key)

    with (
        patch("status_updater._save_status_subpage", side_effect=track_save),
        patch("status_updater._get_authenticated_site", return_value=MagicMock()),
    ):
        status_updater.run_status_cron_update()

    assert "current_job" not in written_keys
    assert "last_job" not in written_keys


def test_run_status_cron_update_uses_configurable_text(monkeypatch):
    import status_updater

    monkeypatch.setenv("NOTDEV", "1")
    monkeypatch.setenv("STATUS_CRON_EDITING", "Watching")
    monkeypatch.setenv("STATUS_CRON_WEB", "Degraded")
    monkeypatch.setenv("STATUS_CRON_DETAILS", "Custom heartbeat")

    written = {}

    def track_save(site, key, text):
        written[key] = text

    with (
        patch("status_updater._save_status_subpage", side_effect=track_save),
        patch("status_updater._get_authenticated_site", return_value=MagicMock()),
    ):
        status_updater.run_status_cron_update()

    assert written["editing"] == "Watching"
    assert written["web"] == "Degraded"
    assert written["details"] == "Custom heartbeat"


def test_update_wiki_status_skips_duplicate_inside_configured_interval(monkeypatch):
    import status_updater

    monkeypatch.setenv("NOTDEV", "1")
    monkeypatch.setenv("STATUS_UPDATE_MIN_INTERVAL_SECONDS", "60")

    fields = {
        "editing": "Idle",
        "web": "Online",
        "last_edit": "Unknown",
        "details": "",
        "warning": "",
        "updated": "ignored",
        "current_job": "None",
        "last_job": "None",
    }
    fingerprint = status_updater._status_payload_fingerprint(fields)
    mock_redis = MagicMock()
    mock_redis.get.side_effect = [fingerprint, str(time.time())]

    with (
        patch.object(status_updater, "_redis", mock_redis),
        patch("status_updater._save_status_subpage") as mock_save,
        patch("status_updater._get_authenticated_site", return_value=MagicMock()),
        patch("status_updater.get_last_bot_edit", return_value="Unknown"),
    ):
        status_updater.update_wiki_status("Idle")

    mock_save.assert_not_called()


# ── notify_maintainers ────────────────────────────────────────────────────────


def test_notify_maintainers_noop_when_not_live(monkeypatch):
    import status_updater

    monkeypatch.delenv("NOTDEV", raising=False)

    mock_user_cls = MagicMock()
    with patch("status_updater.pywikibot.User", mock_user_cls):
        status_updater.notify_maintainers(9999, ["Alice", "Bob"])

    mock_user_cls.assert_not_called()


def test_notify_maintainers_posts_to_each_user_talk_page(monkeypatch):
    import status_updater

    monkeypatch.setenv("NOTDEV", "1")

    mock_talk = MagicMock()
    mock_talk.text = ""
    mock_user = MagicMock()
    mock_user.getUserTalkPage.return_value = mock_talk
    mock_site = MagicMock()

    with patch("status_updater.pywikibot.User", return_value=mock_user):
        status_updater.notify_maintainers(9999, ["Alice", "Bob"], site=mock_site)

    # getUserTalkPage called once per user
    assert mock_user.getUserTalkPage.call_count == 2
    # talk page saved once per user
    assert mock_talk.save.call_count == 2


def test_notify_maintainers_includes_batch_id_in_message(monkeypatch):
    import status_updater

    monkeypatch.setenv("NOTDEV", "1")

    mock_talk = MagicMock()
    mock_talk.text = ""
    mock_user = MagicMock()
    mock_user.getUserTalkPage.return_value = mock_talk
    mock_site = MagicMock()

    with patch("status_updater.pywikibot.User", return_value=mock_user):
        status_updater.notify_maintainers(42000, ["Alice"], site=mock_site)

    assert "42000" in mock_talk.text


def test_notify_maintainers_swallows_per_user_exceptions(monkeypatch):
    import status_updater

    monkeypatch.setenv("NOTDEV", "1")

    mock_user = MagicMock()
    mock_user.getUserTalkPage.side_effect = RuntimeError("wiki error")
    mock_site = MagicMock()

    with patch("status_updater.pywikibot.User", return_value=mock_user):
        # Should not raise even when individual notifications fail
        status_updater.notify_maintainers(9999, ["Alice", "Bob"], site=mock_site)


# ── notify_bot_user ───────────────────────────────────────────────────────────


def test_notify_bot_user_noop_when_not_live(monkeypatch):
    import status_updater

    monkeypatch.delenv("NOTDEV", raising=False)

    mock_user_cls = MagicMock()
    with patch("status_updater.pywikibot.User", mock_user_cls):
        status_updater.notify_bot_user(MagicMock(), "BotAccount", 9999)

    mock_user_cls.assert_not_called()


def test_notify_bot_user_posts_to_talk_page(monkeypatch):
    import status_updater

    monkeypatch.setenv("NOTDEV", "1")

    mock_talk = MagicMock()
    mock_talk.text = ""
    mock_user = MagicMock()
    mock_user.getUserTalkPage.return_value = mock_talk
    mock_site = MagicMock()

    with patch("status_updater.pywikibot.User", return_value=mock_user):
        status_updater.notify_bot_user(mock_site, "BotAccount", 9999, edit_count=5)

    mock_talk.save.assert_called_once()
    assert "9999" in mock_talk.text
    assert "5 edit(s)" in mock_talk.text


def test_notify_bot_user_omits_count_when_not_provided(monkeypatch):
    import status_updater

    monkeypatch.setenv("NOTDEV", "1")

    mock_talk = MagicMock()
    mock_talk.text = ""
    mock_user = MagicMock()
    mock_user.getUserTalkPage.return_value = mock_talk
    mock_site = MagicMock()

    with patch("status_updater.pywikibot.User", return_value=mock_user):
        status_updater.notify_bot_user(mock_site, "BotAccount", 9999)

    assert "edit(s)" not in mock_talk.text


def test_notify_bot_user_swallows_exceptions(monkeypatch):
    import status_updater

    monkeypatch.setenv("NOTDEV", "1")

    with patch("status_updater.pywikibot.User", side_effect=RuntimeError("oops")):
        # Should not raise
        status_updater.notify_bot_user(MagicMock(), "BotAccount", 9999)


# ── _count_batch_jobs integration ────────────────────────────────────────────


def test_count_batch_jobs_returns_count_from_db():
    import rollback_queue

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchone.return_value = (3,)

    with patch("rollback_queue.get_conn", return_value=mock_conn):
        count = rollback_queue._count_batch_jobs(12345)

    assert count == 3
    mock_cursor.execute.assert_called_once_with(
        "SELECT COUNT(*) FROM rollback_jobs WHERE batch_id=%s",
        (12345,),
    )


def test_count_batch_jobs_returns_zero_when_no_rows():
    import rollback_queue

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_cursor.fetchone.return_value = None

    with patch("rollback_queue.get_conn", return_value=mock_conn):
        count = rollback_queue._count_batch_jobs(99999)

    assert count == 0
