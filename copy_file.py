# -*- coding: utf-8 -*-
#
# @file copy_File.py
#
# @remark Copyright 2016 Philippe Elie
# @remark Read the file COPYING
#
# @author Philippe Elie

"""Legacy CLI helper for downloading a wiki file with SHA-1 verification.

The source wiki is tried first.  If resolving its file URL raises, the helper
falls back to the same filename on Wikimedia Commons.  The actual transfer and
bounded checksum retries are delegated to :mod:`utils`.  This module retains its
historic positional CLI and Pywikibot behavior for compatibility.
"""

import utils
import pywikibot


def get_filepage(site, djvuname):
    """Resolve a file page on ``site``, falling back to Commons on URL failure.

    ``None`` is returned only when constructing the original ``FilePage`` raises
    ``NoPageError``.  Other URL-resolution errors are treated as evidence that
    the local description refers to a Commons-hosted file.
    """
    try:
        page = pywikibot.FilePage(site, "File:" + djvuname)
    except pywikibot.exceptions.NoPageError:
        page = None

    if page:
        try:
            # Force URL resolution here: a local description page may exist while
            # the underlying media is actually served from Commons.
            page.get_file_url()
        except Exception:
            # Preserve the historical broad fallback for Pywikibot/API failures.
            site = pywikibot.Site(code="commons", fam="commons")
            page = pywikibot.FilePage(site, "File:" + djvuname)

    return page


def copy_file(lang, family, filename, dest):
    """Download one wiki file to ``dest`` and verify its latest-revision SHA-1.

    Transfer success is intentionally not returned; callers observe failures via
    the legacy downloader's exceptions/diagnostics and resulting destination.
    """
    site = pywikibot.Site(lang, family)
    page = get_filepage(site, filename)
    # ``get_file_url`` is the modern spelling of the former ``fileUrl`` API.
    url = page.get_file_url()
    utils.copy_file_from_url(url, dest, page.latest_file_info.sha1)


if __name__ == "__main__":
    import sys

    # Retain the original four-positional-argument command-line contract.
    copy_file(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
