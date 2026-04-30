from __future__ import annotations

import requests

from botconfig import WIKI_API_URL


class MediaWikiClient:
    def __init__(self, api_url: str = WIKI_API_URL):
        self.api_url = api_url

    def get(self, params: dict, timeout: int = 15) -> requests.Response:
        resp = requests.get(self.api_url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp
