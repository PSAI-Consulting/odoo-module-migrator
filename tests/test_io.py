# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""File I/O must never alter the format of a file."""

import codecs

from odoo_module_migrate import tools


def _roundtrip(tmp_path, raw, transform=lambda s: s.replace("old", "new")):
    path = tmp_path / "file.xml"
    path.write_bytes(raw)
    tools._write_content(path, transform(tools._read_content(path)))
    return path.read_bytes()


def test_crlf_preserved(tmp_path):
    assert _roundtrip(tmp_path, b"<a>\r\n  old\r\n</a>\r\n") == b"<a>\r\n  new\r\n</a>\r\n"


def test_lf_preserved(tmp_path):
    assert _roundtrip(tmp_path, b"<a>\n  old\n</a>\n") == b"<a>\n  new\n</a>\n"


def test_bom_preserved(tmp_path):
    raw = codecs.BOM_UTF8 + "é old\r\n".encode()
    assert _roundtrip(tmp_path, raw) == codecs.BOM_UTF8 + "é new\r\n".encode()


def test_no_bom_added(tmp_path):
    assert _roundtrip(tmp_path, "© old\n".encode()) == "© new\n".encode()


def test_cp1252_kept(tmp_path):
    raw = "# Société old\n".encode("cp1252")
    assert _roundtrip(tmp_path, raw) == "# Société new\n".encode("cp1252")


def test_unchanged_file_not_rewritten(tmp_path):
    path = tmp_path / "file.py"
    path.write_bytes(b"x = 1\r\n")
    mtime = path.stat().st_mtime_ns
    tools._write_content(path, tools._read_content(path))
    assert path.stat().st_mtime_ns == mtime


def test_restore_formats_after_direct_write(tmp_path):
    path = tmp_path / "view.xml"
    path.write_bytes(codecs.BOM_UTF8 + b"<odoo>\r\n</odoo>\r\n")
    snapshot = tools.snapshot_formats(tmp_path)
    path.write_text("<odoo>\n<a/>\n</odoo>\n", encoding="utf-8")  # e.g. lxml
    tools.restore_formats(snapshot)
    assert path.read_bytes() == codecs.BOM_UTF8 + b"<odoo>\r\n<a/>\r\n</odoo>\r\n"
