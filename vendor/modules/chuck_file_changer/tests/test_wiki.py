from unittest.mock import MagicMock, patch

from chuck_file_changer.config import COMMONS_SITE_CODE, COMMONS_SITE_FAMILY
from chuck_file_changer.wiki import WikiClient


def test_wiki_client_uses_commons_and_user_agent():
    with (
        patch("chuck_file_changer.wiki.pywikibot.Site") as site,
        patch("chuck_file_changer.wiki.pywikibot.config") as config,
    ):
        site.return_value = MagicMock()
        WikiClient(user_agent_value="ChuckFileChangerTest/1.0")

    site.assert_called_once_with(COMMONS_SITE_CODE, COMMONS_SITE_FAMILY)
    assert config.user_agent_format == "ChuckFileChangerTest/1.0"
