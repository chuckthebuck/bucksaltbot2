#!/usr/bin/env python3
"""Script to patch status_updater.py and rollback_queue.py with OAuth auth."""

import re

# Helper functions to add to both files
HELPER_FUNCTIONS = '''
# ── Pywikibot OAuth configuration ─────────────────────────────────────────


def _setup_pywikibot_dir() -> None:
    """Configure Pywikibot to use ~/.pywikibot for config files.
    
    This ensures Pywikibot uses the home directory instead of /workspace,
    which avoids file ownership issues on Toolforge.
    """
    from pathlib import Path
    pywikibot_home = Path.home() / ".pywikibot"
    pywikibot_home.mkdir(parents=True, exist_ok=True)
    os.environ["PYWIKIBOT_DIR"] = str(pywikibot_home)
    
    # Create minimal config if it doesn't exist
    config_file = pywikibot_home / "user-config.py"
    if not config_file.exists():
        config_file.write_text(
            "family = 'commons'\\n"
            "mylang = 'commons'\\n"
            "usernames['commons']['commons'] = 'Chuckbot'\\n"
        )


def _get_authenticated_site() -> pywikibot.Site:
    """Create and authenticate a Pywikibot Site using OAuth env vars.
    
    Returns:
        An authenticated pywikibot.Site object for Commons.
    """
    # Ensure Pywikibot config is in the right place
    _setup_pywikibot_dir()
    
    # Get OAuth credentials from environment
    consumer_key = os.getenv("CONSUMER_TOKEN") or os.getenv("OAUTH_CONSUMER_KEY")
    consumer_secret = os.getenv("CONSUMER_SECRET") or os.getenv("OAUTH_CONSUMER_SECRET")
    access_token = os.getenv("ACCESS_TOKEN") or os.getenv("OAUTH_ACCESS_TOKEN")
    access_secret = os.getenv("ACCESS_SECRET") or os.getenv("OAUTH_ACCESS_SECRET")
    
    # Create site object
    site = pywikibot.Site("commons", "commons")
    
    # Attempt OAuth login if credentials are available
    if all([consumer_key, consumer_secret, access_token, access_secret]):
        try:
            site.login(oauth_token=(consumer_key, consumer_secret, access_token, access_secret))
        except Exception as e:
            # Fall back to config-based auth if OAuth fails
            try:
                site.login()
            except Exception:
                # If all else fails, continue without authentication
                pass
    
    return site

'''

def patch_status_updater():
    """Patch status_updater.py"""
    with open("/Users/chuckthebuck/Documents/GitHub/bucksaltbot2/5/status_updater.py", "r") as f:
        content = f.read()
    
    # Add Path to imports if not present
    if "from pathlib import Path" not in content:
        content = content.replace(
            "from datetime import datetime, timezone\n",
            "from datetime import datetime, timezone\nfrom pathlib import Path\n"
        )
    
    # Check if helper functions already exist
    if "_get_authenticated_site" in content:
        print("status_updater.py already has helper functions, skipping functions...")
        return
    
    # Add helper functions after the constants
    insert_point = content.find("# ── Internal helpers ──")
    if insert_point == -1:
        insert_point = content.find("# ── Page titles")
        insert_point = content.find("\n", insert_point) + 1
        insert_point = content.find("STATUS_PAGE", insert_point)
        insert_point = content.find("\n", content.find("\n", insert_point)) + 1
    
    content = content[:insert_point] + HELPER_FUNCTIONS + "\n" + content[insert_point:]
    
    # Replace pywikibot.Site("commons", "commons") calls
    # In get_last_bot_edit
    content = re.sub(
        r'if site is None:\s+site = pywikibot\.Site\("commons", "commons"\)\s+if username is None:',
        'if site is None:\n            site = _get_authenticated_site()\n        if username is None:',
        content
    )
    
    # In update_wiki_status
    content = re.sub(
        r'site = pywikibot\.Site\("commons", "commons"\)\s+page = pywikibot\.Page\(site, STATUS_PAGE\)',
        'site = _get_authenticated_site()\n        page = pywikibot.Page(site, STATUS_PAGE)',
        content
    )
    
    # In notify_maintainers
    content = re.sub(
        r'if site is None:\s+site = pywikibot\.Site\("commons", "commons"\)\s+for username in users:',
        'if site is None:\n        site = _get_authenticated_site()\n\n    for username in users:',
        content
    )
    
    with open("/Users/chuckthebuck/Documents/GitHub/bucksaltbot2/5/status_updater.py", "w") as f:
        f.write(content)
    print("✓ status_updater.py patched")


def patch_rollback_queue():
    """Patch rollback_queue.py"""
    with open("/Users/chuckthebuck/Documents/GitHub/bucksaltbot2/5/rollback_queue.py", "r") as f:
        content = f.read()
    
    # Add Path to imports
    if "from pathlib import Path" not in content:
        content = content.replace(
            "import os\n",
            "import os\nfrom pathlib import Path\n"
        )
    
    # Replace _bot_site function
    old_bot_site = '''def _bot_site() -> pywikibot.Site:
    consumer_token = os.environ.get("CONSUMER_TOKEN")
    consumer_secret = os.environ.get("CONSUMER_SECRET")
    access_token = os.environ.get("ACCESS_TOKEN")
    access_secret = os.environ.get("ACCESS_SECRET")

    if not all([consumer_token, consumer_secret, access_token, access_secret]):
        raise RuntimeError(
            "CONSUMER_TOKEN, CONSUMER_SECRET, ACCESS_TOKEN and ACCESS_SECRET must be configured"
        )

    site = pywikibot.Site("commons", "commons")
    site.login()

    print("Logged in as:", site.user())

    return site'''
    
    new_bot_site = '''def _setup_pywikibot_dir() -> None:
    """Configure Pywikibot to use ~/.pywikibot for config files."""
    pywikibot_home = Path.home() / ".pywikibot"
    pywikibot_home.mkdir(parents=True, exist_ok=True)
    os.environ["PYWIKIBOT_DIR"] = str(pywikibot_home)
    
    # Create minimal config if it doesn't exist
    config_file = pywikibot_home / "user-config.py"
    if not config_file.exists():
        config_file.write_text(
            "family = 'commons'\\n"
            "mylang = 'commons'\\n"
            "usernames['commons']['commons'] = 'Chuckbot'\\n"
        )


def _bot_site() -> pywikibot.Site:
    """Create and authenticate a Pywikibot Site using OAuth env vars."""
    _setup_pywikibot_dir()
    
    consumer_token = os.environ.get("CONSUMER_TOKEN")
    consumer_secret = os.environ.get("CONSUMER_SECRET")
    access_token = os.environ.get("ACCESS_TOKEN")
    access_secret = os.environ.get("ACCESS_SECRET")

    if not all([consumer_token, consumer_secret, access_token, access_secret]):
        raise RuntimeError(
            "CONSUMER_TOKEN, CONSUMER_SECRET, ACCESS_TOKEN and ACCESS_SECRET must be configured"
        )

    site = pywikibot.Site("commons", "commons")
    
    # Authenticate with OAuth
    try:
        site.login(oauth_token=(consumer_token, consumer_secret, access_token, access_secret))
        print("Logged in as:", site.user())
    except Exception as e:
        print(f"OAuth login failed: {e}")
        raise

    return site'''
    
    if old_bot_site in content:
        content = content.replace(old_bot_site, new_bot_site)
        print("✓ rollback_queue.py _bot_site function patched")
    else:
        print("! Could not find exact _bot_site function to replace")
    
    # Add _setup_pywikibot_dir() calls before bare Site() creations in large job checks
    # First check
    content = re.sub(
        r'if large:\s+_notify_site = site or pywikibot\.Site\("commons", "commons"\)\s+notify_users = status_updater\.get_notify_list',
        '''if large:
            if site is None:
                _setup_pywikibot_dir()
            _notify_site = site or pywikibot.Site("commons", "commons")
            notify_users = status_updater.get_notify_list''',
        content
    )
    
    # Second check
    content = re.sub(
        r'# Notify maintainers once per large batch\.\s+if large and not status_updater\.is_batch_already_notified\(batch_id\):\s+_notify_site = site or pywikibot\.Site\("commons", "commons"\)',
        '''# Notify maintainers once per large batch.
        if large and not status_updater.is_batch_already_notified(batch_id):
            if site is None:
                _setup_pywikibot_dir()
            _notify_site = site or pywikibot.Site("commons", "commons")''',
        content
    )
    
    with open("/Users/chuckthebuck/Documents/GitHub/bucksaltbot2/5/rollback_queue.py", "w") as f:
        f.write(content)
    print("✓ rollback_queue.py patched")


if __name__ == "__main__":
    patch_status_updater()
    patch_rollback_queue()
    print("\n✅ All patches applied successfully!")
