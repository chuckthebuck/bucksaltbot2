"""Tests for utils.py – file I/O, hashing, and compression utilities."""

import bz2
import gzip
import hashlib
import os

import pytest

import utils


# ── read_file / write_file ────────────────────────────────────────────────────


def test_read_file_returns_file_contents(tmp_path):
    f = tmp_path / "sample.txt"
    f.write_text("hello world", encoding="utf-8")
    assert utils.read_file(str(f)) == "hello world"


def test_write_file_is_python2_legacy_and_raises_in_python3(tmp_path):
    """write_file() opens the file in text mode then calls str.encode(), which
    produces bytes.  In Python 3 writing bytes to a text-mode file raises
    TypeError.  This documents the known Python 2-only compatibility of the
    function; it should not be used in Python 3 code paths."""
    f = tmp_path / "out.txt"
    with pytest.raises(TypeError):
        utils.write_file(str(f), "hello")


# ── sha1 ──────────────────────────────────────────────────────────────────────


def test_sha1_returns_correct_hex_digest(tmp_path):
    f = tmp_path / "data.bin"
    data = b"test data"
    f.write_bytes(data)
    expected = hashlib.sha1(data).hexdigest()
    assert utils.sha1(str(f)) == expected


def test_sha1_returns_40_char_hex_string(tmp_path):
    f = tmp_path / "data.bin"
    f.write_bytes(b"some content")
    result = utils.sha1(str(f))
    assert len(result) == 40
    assert all(c in "0123456789abcdef" for c in result)


# ── write_sha1 ────────────────────────────────────────────────────────────────


def test_write_sha1_persists_hash_to_file(tmp_path):
    f = tmp_path / "hash.sha1"
    utils.write_sha1("abc123", str(f))
    assert f.read_text() == "abc123"


# ── compress_file_data ────────────────────────────────────────────────────────


def test_compress_file_data_bzip2(tmp_path):
    out = str(tmp_path / "data")
    utils.compress_file_data(out, b"hello bzip2", "bzip2")
    assert os.path.exists(out + ".bz2")
    assert bz2.decompress(open(out + ".bz2", "rb").read()) == b"hello bzip2"


def test_compress_file_data_gzip(tmp_path):
    out = str(tmp_path / "data")
    utils.compress_file_data(out, b"hello gzip", "gzip")
    assert os.path.exists(out + ".gz")
    with gzip.open(out + ".gz", "rb") as fh:
        assert fh.read() == b"hello gzip"


def test_compress_file_data_raises_for_unknown_scheme(tmp_path):
    with pytest.raises(ValueError, match="Unhandled compression scheme"):
        utils.compress_file_data(str(tmp_path / "data"), b"x", "lzma")


# ── uncompress_file ───────────────────────────────────────────────────────────


def test_uncompress_file_bzip2_round_trip(tmp_path):
    base = str(tmp_path / "data")
    utils.compress_file_data(base, b"bz2 content", "bzip2")
    result = utils.uncompress_file(base, "bzip2")
    assert result == b"bz2 content"


def test_uncompress_file_gzip_round_trip(tmp_path):
    base = str(tmp_path / "data")
    utils.compress_file_data(base, b"gz content", "gzip")
    result = utils.uncompress_file(base, "gzip")
    assert result == b"gz content"


def test_uncompress_file_returns_none_when_file_missing(tmp_path):
    result = utils.uncompress_file(str(tmp_path / "nonexistent"), "bzip2")
    assert result is None


def test_uncompress_file_raises_for_unknown_scheme(tmp_path):
    with pytest.raises(ValueError, match="Unhandled compression scheme"):
        utils.uncompress_file(str(tmp_path / "f"), "lzma")


def test_uncompress_file_plain_round_trip(tmp_path):
    f = tmp_path / "plain.txt"
    f.write_text("plain text", encoding="utf-8")
    result = utils.uncompress_file(str(f), "")
    # The "" scheme opens in text mode, so the result is a str, not bytes.
    assert result == "plain text"


def test_uncompress_file_list_tries_all_schemes(tmp_path):
    """uncompress_file accepts a list of schemes and returns the first match."""
    base = str(tmp_path / "data")
    utils.compress_file_data(base, b"multi", "gzip")
    result = utils.uncompress_file(base, ["bzip2", "gzip"])
    assert result == b"multi"


# ── readline_backward ─────────────────────────────────────────────────────────


def test_readline_backward_yields_lines_in_reverse(tmp_path):
    f = tmp_path / "lines.txt"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")
    lines = list(utils.readline_backward(str(f)))
    # Reverse order; trailing empty lines may vary
    non_empty = [line for line in lines if line]
    assert non_empty == ["line3", "line2", "line1"]
