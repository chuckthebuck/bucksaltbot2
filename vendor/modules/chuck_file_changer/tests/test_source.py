from chuck_file_changer import source


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_resolve_user_uploads_uses_logevents(monkeypatch):
    calls = []

    def fake_get(url, *, params, headers, timeout):
        calls.append(params)
        return Response(
            {
                "query": {
                    "logevents": [
                        {
                            "action": "upload",
                            "title": "File:One.jpg",
                            "timestamp": "2026-01-01T00:00:00Z",
                        }
                    ]
                }
            }
        )

    monkeypatch.setattr(source.requests, "get", fake_get)

    targets, source_url = source.resolve_vfc_source(
        {"source_mode": "user", "source_target": "Alice", "source_sort": "oldest"}
    )

    assert targets[0].title == "File:One.jpg"
    assert targets[0].user == "Alice"
    assert calls[0]["list"] == "logevents"
    assert calls[0]["letype"] == "upload"
    assert calls[0]["ledir"] == "newer"
    assert "source_mode=user" in source_url


def test_resolve_user_uploads_accepts_user_page_title_and_overwrites(monkeypatch):
    calls = []

    def fake_get(url, *, params, headers, timeout):
        calls.append(params)
        return Response(
            {"query": {"logevents": [{"action": "overwrite", "title": "File:One.jpg"}]}}
        )

    monkeypatch.setattr(source.requests, "get", fake_get)
    targets, _source_url = source.resolve_vfc_source(
        {"source_mode": "user", "source_target": "User:Alice"}
    )

    assert targets[0].user == "Alice"
    assert calls[0]["leuser"] == "Alice"


def test_resolve_category_members(monkeypatch):
    def fake_get(url, *, params, headers, timeout):
        assert params["list"] == "categorymembers"
        assert params["cmtype"] == "file"
        assert params["cmtitle"] == "Category:Example"
        return Response(
            {
                "query": {
                    "categorymembers": [
                        {"title": "File:One.jpg"},
                        {"title": "File:One.jpg"},
                        {"title": "File:Two.jpg"},
                    ]
                }
            }
        )

    monkeypatch.setattr(source.requests, "get", fake_get)

    targets, _source_url = source.resolve_vfc_source(
        {"source_mode": "category", "source_target": "Example"}
    )

    assert [target.title for target in targets] == ["File:One.jpg", "File:Two.jpg"]


def test_resolve_page_images(monkeypatch):
    def fake_get(url, *, params, headers, timeout):
        assert params["prop"] == "images"
        assert params["titles"] == "Commons:Example gallery"
        return Response(
            {
                "query": {
                    "pages": [
                        {"title": "Commons:Example gallery", "images": [{"title": "File:One.jpg"}]}
                    ]
                }
            }
        )

    monkeypatch.setattr(source.requests, "get", fake_get)

    targets, _source_url = source.resolve_vfc_source(
        {"source_mode": "page", "source_target": "Commons:Example gallery"}
    )

    assert targets[0].title == "File:One.jpg"


def test_resolve_search_limits_to_file_namespace(monkeypatch):
    def fake_get(url, *, params, headers, timeout):
        assert params["list"] == "search"
        assert params["srnamespace"] == 6
        return Response({"query": {"search": [{"title": "File:One.jpg"}]}})

    monkeypatch.setattr(source.requests, "get", fake_get)

    targets, _source_url = source.resolve_vfc_source(
        {"source_mode": "search", "source_target": "insource:Example"}
    )

    assert targets[0].title == "File:One.jpg"
