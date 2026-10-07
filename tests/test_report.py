# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import logging
import pathlib

from odoo_module_migrate import report


def _collect(tmp_path, messages):
    module = tmp_path / "my_module"
    module.mkdir()
    collector = report.ReportCollector([("my_module", module), ("my_module_ext", tmp_path / "my_module_ext")])
    collector.current = collector.reports["my_module"]
    log = logging.getLogger("test_report")
    log.addHandler(collector)
    log.setLevel(logging.INFO)
    for level, message in messages:
        log.log(level, message.replace("<M>", str(module)))
    log.removeHandler(collector)
    return collector.reports["my_module"]


def test_entries_located_and_deduplicated(tmp_path):
    rep = _collect(tmp_path, [
        (logging.WARNING, r"Field res.partner.mobile was removed (self.mobile) - OpenUpgrade 19.0 x/upgrade_analysis.txt. File <M>\models\partner.py:17"),
        (logging.WARNING, r"Field res.partner.mobile was removed (self.mobile) - OpenUpgrade 19.0 x/upgrade_analysis.txt. File <M>\models\partner.py:17"),
        (logging.ERROR, "[view] field 'type' not found. File <M>/views/product.xml:44"),
        (logging.INFO, "Updated tree->list in: <M>/views/product.xml"),
        (logging.INFO, "Dependency 'stock_picking_batch' replaced by 'stock' (merged). File <M>/__manifest__.py"),
    ])
    assert len(rep.todos) == 2 and len(rep.errors) == 1
    assert rep.risk == "élevé"
    warning = rep.todos[0]
    assert (warning.file, warning.line) == ("models/partner.py", 17)
    assert warning.source.startswith("OpenUpgrade 19.0")
    assert [e.message for e in rep.transformations] == ["Updated tree->list"]
    assert rep.depends[0].file == "__manifest__.py"

    text = report.render(rep, "17.0", "20.0", ["views/product.xml"])
    assert "[`views/product.xml:44`](views/product.xml#L44)" in text
    assert "- [ ] 🔴 erreur" in text
    assert "## Dépendances" in text


def test_longest_module_path_wins(tmp_path):
    (tmp_path / "my_module_ext").mkdir()
    collector = report.ReportCollector([
        ("my_module", tmp_path / "my_module"), ("my_module_ext", tmp_path / "my_module_ext"),
    ])
    found, relative, line, _ = collector._locate(f"x. File {tmp_path / 'my_module_ext' / 'a.py'}:3")
    assert (found.name, relative, line) == ("my_module_ext", "a.py", 3)


def test_no_todo_means_no_risk():
    rep = report.ModuleReport("m", pathlib.Path("."))
    assert rep.risk == "aucun"
    assert "Aucun." in report.render(rep, "18.0", "19.0")


def test_summary_accepts_unknown_risk():
    rep = report.ModuleReport("m", pathlib.Path("."))
    rep.entries.append(report.Entry("WARNING", "[incomplete] missing dependency"))
    assert rep.risk == "inconnu"
    text = report.render_summary([rep], "17.0", "20.0")
    assert "| [m](m.md) | inconnu |" in text
