"""Characterize the legacy file, hashing, and compression helpers in ``utils``."""

import bz2
import gzip
import hashlib
import os

import pytest

import utils


# ── read_file / write_file ────────────────────────────────────────────────────


def test_read_file_returns_file_contents(tmp_path):
    """Read UTF-8 text from the path supplied to ``read_file``."""
    f = tmp_path / "sample.txt"
    f.write_text("hello world", encoding="utf-8")
    assert utils.read_file(str(f)) == "hello world"


def test_write_file_is_python2_legacy_and_raises_in_python3(tmp_path):
    """Preserve the known Python 3 failure of the Python 2-era writer.

    ``write_file`` opens in text mode but encodes its input to bytes. Python 3
    therefore raises ``TypeError`` instead of writing the payload; callers
    should not use this helper on current code paths.
    """
    f = tmp_path / "out.txt"
    with pytest.raises(TypeError):
        utils.write_file(str(f), "hello")


# ── sha1 ──────────────────────────────────────────────────────────────────────


def test_sha1_returns_correct_hex_digest(tmp_path):
    """Hash the exact bytes stored on disk using SHA-1."""
    f = tmp_path / "data.bin"
    data = b"test data"
    f.write_bytes(data)
    expected = hashlib.sha1(data).hexdigest()
    assert utils.sha1(str(f)) == expected


def test_sha1_returns_40_char_hex_string(tmp_path):
    """Return the digest in canonical lowercase hexadecimal form."""
    f = tmp_path / "data.bin"
    f.write_bytes(b"some content")
    result = utils.sha1(str(f))
    assert len(result) == 40
    assert all(c in "0123456789abcdef" for c in result)


# ── write_sha1 ────────────────────────────────────────────────────────────────


def test_write_sha1_persists_hash_to_file(tmp_path):
    """Persist a precomputed digest without altering its text."""
    f = tmp_path / "hash.sha1"
    utils.write_sha1("abc123", str(f))
    assert f.read_text() == "abc123"


# ── compress_file_data ────────────────────────────────────────────────────────


def test_compress_file_data_bzip2(tmp_path):
    """Write bzip2 data to the base path with the expected suffix."""
    out = str(tmp_path / "data")
    # The helper owns suffix selection; callers pass an unsuffixed base path.
    utils.compress_file_data(out, b"hello bzip2", "bzip2")
    assert os.path.exists(out + ".bz2")
    assert bz2.decompress(open(out + ".bz2", "rb").read()) == b"hello bzip2"


def test_compress_file_data_gzip(tmp_path):
    """Write gzip data that the standard-library reader can recover."""
    out = str(tmp_path / "data")
    utils.compress_file_data(out, b"hello gzip", "gzip")
    assert os.path.exists(out + ".gz")
    with gzip.open(out + ".gz", "rb") as fh:
        assert fh.read() == b"hello gzip"


def test_compress_file_data_raises_for_unknown_scheme(tmp_path):
    """Reject compression schemes for which no writer is registered."""
    with pytest.raises(ValueError, match="Unhandled compression scheme"):
        utils.compress_file_data(str(tmp_path / "data"), b"x", "lzma")


# ── uncompress_file ───────────────────────────────────────────────────────────


def test_uncompress_file_bzip2_round_trip(tmp_path):
    """Recover bytes previously written through the bzip2 branch."""
    base = str(tmp_path / "data")
    utils.compress_file_data(base, b"bz2 content", "bzip2")
    result = utils.uncompress_file(base, "bzip2")
    assert result == b"bz2 content"


def test_uncompress_file_gzip_round_trip(tmp_path):
    """Recover bytes previously written through the gzip branch."""
    base = str(tmp_path / "data")
    utils.compress_file_data(base, b"gz content", "gzip")
    result = utils.uncompress_file(base, "gzip")
    assert result == b"gz content"


def test_uncompress_file_returns_none_when_file_missing(tmp_path):
    """Represent a missing compressed candidate with ``None``."""
    result = utils.uncompress_file(str(tmp_path / "nonexistent"), "bzip2")
    assert result is None


def test_uncompress_file_raises_for_unknown_scheme(tmp_path):
    """Reject decompression schemes for which no reader is registered."""
    with pytest.raises(ValueError, match="Unhandled compression scheme"):
        utils.uncompress_file(str(tmp_path / "f"), "lzma")


def test_uncompress_file_plain_round_trip(tmp_path):
    """Use an empty scheme to read an unsuffixed file as text."""
    f = tmp_path / "plain.txt"
    f.write_text("plain text", encoding="utf-8")
    result = utils.uncompress_file(str(f), "")
    # The "" scheme opens in text mode, so the result is a str, not bytes.
    assert result == "plain text"


def test_uncompress_file_list_tries_all_schemes(tmp_path):
    """Try candidate schemes in order and return the first existing file."""
    base = str(tmp_path / "data")
    utils.compress_file_data(base, b"multi", "gzip")
    result = utils.uncompress_file(base, ["bzip2", "gzip"])
    assert result == b"multi"


# ── readline_backward ─────────────────────────────────────────────────────────


def test_readline_backward_yields_lines_in_reverse(tmp_path):
    """Yield a newline-terminated text file from its last line to its first."""
    f = tmp_path / "lines.txt"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")
    lines = list(utils.readline_backward(str(f)))
    # Ignore empty boundary records so the assertion targets line ordering.
    non_empty = [line for line in lines if line]
    assert non_empty == ["line3", "line2", "line1"]
