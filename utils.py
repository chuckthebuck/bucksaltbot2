#!/usr/bin/python
# -*- coding: utf-8 -*-

"""Legacy file, download, compression, logging, and reverse-read utilities.

These helpers originated in a Python 2 codebase and intentionally retain several
mixed text/bytes conventions for callers that still depend on them.  In
particular, :func:`write_file` and :func:`compress_file` are not Python 3-safe;
new code should use explicit encodings/binary modes instead.  The focused tests
document the compatibility surface that remains supported.
"""

from urllib.request import URLopener as urllib_URLopener
from urllib.parse import quote as urllib_quote

import hashlib
import bz2
import gzip
import os
import errno
import sys
import time
import io


def read_file(filename):
    """Read an entire text file using the legacy version-dependent decode path."""
    fd = open(filename)
    if sys.version_info >= (3, 0):
        text = fd.read()
    else:
        text = fd.read().decode("utf-8")
    fd.close()
    return text


def write_file(filename, text):
    """Write UTF-8 bytes through the historical Python 2 text-file path.

    On Python 3, ``text.encode`` produces bytes and writing them to this text-mode
    descriptor raises ``TypeError``.  That behavior is retained for compatibility
    and explicitly covered by tests; this helper is not for new Python 3 paths.
    """
    fd = open(filename, "w")
    fd.write(text.encode("utf-8"))
    fd.close()


def sha1(filename):
    """Return the lowercase SHA-1 hex digest of a file read in 4 KiB chunks."""
    fd = io.open(filename, "rb")
    h = hashlib.sha1()
    data = True
    # Streaming avoids loading potentially large wiki media files into memory.
    while data:
        data = fd.read(4096)
        if data:
            h.update(data)
    fd.close()

    return h.hexdigest()


def write_sha1(sha1, filename):
    """Persist a precomputed digest verbatim to a text file."""
    fd = open(filename, "w")
    fd.write(sha1)
    fd.close()


def url_opener():
    """Create the legacy URL opener with the historical tool User-Agent."""
    opener = urllib_URLopener()
    opener.addheaders = [("User-agent", "MW_phetools")]
    return opener


def copy_file_from_url(url, out_file, expect_sha1=None, max_retry=4):
    """Download a URL with optional SHA-1 verification and bounded retries.

    Retry count is clamped to one through five attempts.  Checksum mismatches use
    exponentially increasing waits; a matching digest (or no expected digest)
    marks success.  The old ``URLopener``-shaped HTTP 302 exception is followed
    recursively.  The function returns a boolean and may leave the last
    checksum-mismatched file for diagnostics.
    """
    retry = 0
    # Prevent callers from disabling the initial attempt or creating unbounded
    # retry loops through an extreme value.
    max_retry = min(max(1, max_retry), 5)
    ok = False
    # Quote spaces/non-ASCII characters without escaping URL structure or an
    # already percent-encoded path.
    url = urllib_quote(url, safe=":/%")
    while not ok and retry < max_retry:
        try:
            opener = url_opener()
            fd_in = opener.open(url)
            fd_out = open(out_file, "wb")
            data = True
            while data:
                data = fd_in.read(4096)
                if data:
                    fd_out.write(data)
            fd_in.close()
            fd_out.close()
            if expect_sha1:
                # MediaWiki exposes the latest file SHA-1; compare only after the
                # complete response has been flushed and closed.
                if sha1(out_file) != expect_sha1:
                    retry += 1
                    if retry < max_retry:
                        time.sleep(60 * (retry << 1))
                else:
                    ok = True
            else:
                ok = True
        except IOError as e:
            # Compatibility with the tuple-shaped redirect error emitted by the
            # deprecated URLopener implementation.
            if e.args[0] == "http error" and e.args[1] == 302:
                new_url = e.args[3]["Location"]
                return copy_file_from_url(new_url, out_file, expect_sha1, max_retry - 1)
            raise
        except Exception:
            print_traceback("upload error:", url, out_file)
            if os.path.exists(out_file):
                os.remove(out_file)
            retry += 1
            if retry < max_retry:
                time.sleep(60 * (retry << 1))

    if retry:
        if ok:
            print(
                "upload success after %d retry" % retry, url, out_file, file=sys.stderr
            )
        else:
            print(
                "upload failure after %d retry" % retry, url, out_file, file=sys.stderr
            )

    return ok


def compress_file_data(out_filename, data, compress_type):
    """Compress byte data to ``.bz2`` or ``.gz`` beside a base output name."""
    if compress_type in ["bzip2", "gzip"]:
        if compress_type == "bzip2":
            with bz2.BZ2File(out_filename + ".bz2", "wb") as f_out:
                f_out.write(data)
        else:
            with gzip.open(out_filename + ".gz", "wb") as f_out:
                f_out.write(data)
    else:
        raise ValueError("Unhandled compression scheme: " + str(compress_type))


def compress_file(out_filename, in_filename, compress_type):
    """Compress data read through the historical text-mode input path.

    This preserves Python 2 semantics; on Python 3 the resulting ``str`` is not
    accepted by the binary compression writers.
    """
    f_in = open(in_filename)
    compress_file_data(out_filename, f_in.read(), compress_type)
    f_in.close()


def uncompress_file(filename, compress_type):
    """Read the first available compressed/plain variant.

    ``compress_type`` may be one scheme or an ordered list to probe.  Missing
    variants return ``None``; empty content remains a distinct bytes/string value.
    Bzip2/gzip reads return bytes, while the empty-string plain scheme uses text
    mode and returns ``str``.  Unknown schemes raise ``ValueError``.
    """
    if isinstance(compress_type, list):
        # Ordering is caller-controlled, allowing a preferred compression format
        # with transparent fallback to another on-disk representation.
        for compress in compress_type:
            data = uncompress_file(filename, compress)
            if data is not None:
                return data
        return None
    else:
        fd_in = None
        if compress_type == "bzip2":
            if os.path.exists(filename + ".bz2"):
                fd_in = bz2.BZ2File(filename + ".bz2")
        elif compress_type == "gzip":
            if os.path.exists(filename + ".gz"):
                fd_in = gzip.open(filename + ".gz")
        elif compress_type == "":
            if os.path.exists(filename):
                fd_in = open(filename)
        else:
            raise ValueError("Unhandled compression scheme: " + str(compress_type))

        if fd_in is None:
            return None
        data = fd_in.read()
        fd_in.close()
        return data

    raise ValueError("Empty compression scheme: " + str(compress_type))


def _retry_on_eintr(func, *args):
    """Retry a file-descriptor operation only when interrupted by ``EINTR``."""
    while True:
        try:
            return func(*args)
        except (IOError, OSError) as e:
            # print "EINTR, retrying"
            if e.errno != errno.EINTR:
                raise
            continue


def safe_read(fd):
    """Call ``fd.read`` and transparently retry interrupted system calls."""
    return _retry_on_eintr(fd.read)


def safe_write(fd, text):
    """Call ``fd.write(text)`` and transparently retry interrupted system calls."""
    return _retry_on_eintr(fd.write, text)


def print_traceback(*kwargs):
    """Print the active traceback and optional context to a logger and stderr.

    The final positional value is the legacy logger object and must provide
    ``get_file_handler``; all preceding values are diagnostic context.  String
    context is UTF-8 encoded for the logger path to preserve historical output.
    """
    logger = kwargs[-1]
    kwargs = kwargs[:-1]
    import traceback

    try:
        traceback.print_exc(file=logger.get_file_handler())
        traceback.print_exc(file=sys.stderr)
        if len(kwargs):
            print("arguments:", file=logger.get_file_handler())
            print("arguments:", file=sys.stderr)
            for f in kwargs:
                if isinstance(f, str):
                    f = f.encode("utf-8")
                print(f, file=logger.get_file_handler())
                print(str(f), file=sys.stderr)
    except:
        print("ERROR: An exception occured during traceback", file=sys.stderr)
        raise


# File can be written during reading but it's assumed write are line buffered
# or caller must ignore the first line because it can be a partial line.
def readline_backward(filename, buf_size=8192):
    """Yield a text file's lines from end to start in bounded blocks.

    A trailing newline does not produce an initial empty result.  The file may be
    appended while being read when writes are line-buffered; otherwise the first
    yielded line may be partial and callers must ignore it.  An empty file follows
    the legacy behavior of yielding ``None`` once.
    """
    with open(filename) as fh:
        offset = 0
        partial_line = None
        fh.seek(0, os.SEEK_END)
        total_size = left_size = fh.tell()
        # Start with the short tail block so subsequent seeks align to buf_size.
        block_size = total_size % buf_size
        first = True
        while left_size:
            offset = min(total_size, offset + block_size)
            fh.seek(total_size - offset, os.SEEK_SET)
            buf = fh.read(min(left_size, block_size))
            left_size = max(0, left_size - block_size)
            lines = buf.split("\n")
            if first:
                # The first block can end with a \n, remove it else
                # we will get an empty line at start of output.
                if not lines[-1]:
                    lines = lines[:-1]
                # After the first block read the full buffer size.
                block_size = buf_size
            first = False
            if partial_line:
                # Join the leading fragment of the later block to the trailing
                # fragment just read from the preceding block.
                lines[-1] += partial_line
            partial_line = lines[0]
            for index in range(len(lines) - 1, 0, -1):
                yield lines[index]
        yield partial_line
