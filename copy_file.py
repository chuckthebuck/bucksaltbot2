# -*- coding: utf-8 -*-
#
# @file copy_File.py
#
# @remark Copyright 2016 Philippe Elie
# @remark Read the file COPYING
#
# @author Philippe Elie

import utils
import pywikibot

def get_filepage(site, djvuname):
    try:
        page = pywikibot.FilePage(site, "File:" + djvuname)
    except pywikibot.exceptions.NoPageError:
        page = None

    if page:
        try:
#            page.fileUrl()
            page.get_file_url()
        except:
            site = pywikibot.Site(code = 'commons', fam = 'commons')
            page = pywikibot.FilePage(site, "File:" + djvuname)

    return page

def copy_file(lang, family, filename, dest):
    site = pywikibot.Site(lang, family)
    page = get_filepage(site, filename)
#    url = page.fileUrl()
    url = page.get_file_url()
    utils.copy_file_from_url(url, dest, page.latest_file_info.sha1)

if __name__ == "__main__":
    import sys
    copy_file(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
