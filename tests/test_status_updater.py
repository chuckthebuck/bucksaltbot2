"""Tests for status_updater.py."""

from unittest.mock import MagicMock, patch


def test_resolve_pywikibot_dir_falls_back_from_unwritable_home(monkeypatch):
    import status_updater

    monkeypatch.delenv("PYWIKIBOT_DIR", raising=False)
    monkeypatch.setenv("HOME", "/data/project/buckbot")

    attempted: list[str] = []

    def fake_mkdir(path_obj, parents=False, exist_ok=False):
        attempted.append(str(path_obj))
        if str(path_obj).startswith("/data/project"):
            raise PermissionError("denied")

    with patch("status_updater.Path.mkdir", new=fake_mkdir):
        resolved = status_updater._resolve_pywikibot_dir()

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

    mock_page.save.assert_called_once()
    save_kwargs = mock_page.save.call_args.kwargs
    assert save_kwargs.get("minor") is True
    assert save_kwargs.get("botflag") is True


def test_update_wiki_status_includes_warning_when_provided(monkeypatch):
    import status_updater

    monkeypatch.setenv("NOTDEV", "1")

    mock_page = MagicMock()

    with (
        patch("status_updater.pywikibot.Site"),
        patch("status_updater.pywikibot.Page", return_value=mock_page),
    ):
        status_updater.update_wiki_status(
            editing="Actively editing",
            warning="Large batch job in progress.",
        )

    assigned_text = mock_page.text
    assert "| warning = Large batch job in progress." in assigned_text


def test_update_wiki_status_omits_warning_field_when_none(monkeypatch):
    import status_updater

    monkeypatch.setenv("NOTDEV", "1")

    mock_page = MagicMock()

    with (
        patch("status_updater.pywikibot.Site"),
        patch("status_updater.pywikibot.Page", return_value=mock_page),
    ):
        status_updater.update_wiki_status("Idle")

    assert "| warning" not in mock_page.text


def test_update_wiki_status_swallows_exceptions(monkeypatch):
    import status_updater

    monkeypatch.setenv("NOTDEV", "1")

    with patch("status_updater.pywikibot.Site", side_effect=RuntimeError("oops")):
        # Should not raise
        status_updater.update_wiki_status("Idle")


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
