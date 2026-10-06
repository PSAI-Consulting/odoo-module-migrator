# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""from odoo.tools import X: rewriting of the imports
(odoo_module_migrate/odoo_tools_imports.py) with the real data of each step."""

import logging
from pathlib import Path

from odoo_module_migrate import odoo_tools_imports as oti
from odoo_module_migrate import tools

SCRIPTS = Path(__file__).resolve().parent.parent / "odoo_module_migrate" / "migration_scripts"


def _rules(step):
    return oti.load_rules(SCRIPTS / "python_scripts" / step / "odoo_tools_imports.yaml")


def _patterns(step):
    return oti.load_error_patterns(SCRIPTS / "text_errors" / step)


def _rewrite(step, text):
    new, reports = oti.rewrite(text, _rules(step), _patterns(step))
    # idempotent, and nothing left to rewrite
    again, _reports = oti.rewrite(new, _rules(step), _patterns(step))
    assert again == new
    return new, [(line, rule["name"], kind) for line, rule, kind in reports]


# ---------------------------------------------------------------- 19.0 -> 20.0


def test_20_moved_names():
    new, reports = _rewrite("migrate_190_200", (
        "from odoo.tools import SQL, Query, street_split, mod10r as m10\n"
        "from odoo.tools import ormcache\n"
    ))
    assert new == (
        "from odoo.tools import SQL\n"
        "from odoo.models import Query\n"
        "from odoo.tools.business_data import street_split, mod10r as m10\n"
        "from odoo.api import ormcache\n"
    )
    assert reports == []


def test_20_query_module():
    new, reports = _rewrite("migrate_190_200", "from odoo.tools.query import Query\n")
    assert new == "from odoo.models import Query\n"
    assert reports == []


def test_20_sql_and_convert():
    new, reports = _rewrite("migrate_190_200", (
        "def f():\n"
        "    from odoo.tools import create_index, index_exists, make_index_name, convert_xml_import\n"
        "    return create_index\n"
    ))
    assert new == (
        "def f():\n"
        "    from odoo.tools.sql import create_index, index_exists, make_index_name\n"
        "    from odoo.tools.convert import convert_xml_import\n"
        "    return create_index\n"
    )
    assert reports == []


def test_20_long_import_wrapped():
    new, reports = _rewrite("migrate_190_200", (
        "class A:\n"
        "    def f(self):\n"
        "        from odoo.tools import (SQL, create_index, index_exists, make_index_name,\n"
        "                                reverse_order, escape_psql, make_identifier, float_round)\n"
    ))
    assert new == (
        "class A:\n"
        "    def f(self):\n"
        "        from odoo.tools import SQL, float_round\n"
        "        from odoo.tools.sql import (\n"
        "            create_index,\n"
        "            index_exists,\n"
        "            make_index_name,\n"
        "            reverse_order,\n"
        "            escape_psql,\n"
        "            make_identifier,\n"
        "        )\n"
    )
    assert reports == []


def test_20_removed_reported_once():
    # ustr / ormcache_context: already reported by text_errors/migrate_190_200/core_api.yaml
    new, reports = _rewrite("migrate_190_200", (
        "from odoo.tools import ustr, ormcache_context, convert_sql_import, discardattr\n"
    ))
    assert new == (
        "from odoo.tools import ustr, ormcache_context, convert_sql_import\n"
        "from odoo.orm.model_classes import discardattr\n"
    )
    assert reports == [(1, "convert_sql_import", "removed")]


def test_20_tools_attribute_reported():
    text = "from odoo import models, tools\n\nx = tools.street_split('a 1')\ny = tools.ormcache\nz = tools.SQL\n"
    new, reports = _rewrite("migrate_190_200", text)
    assert new == text
    assert reports == [(3, "street_split", "attribute")]


def test_already_qualified_untouched():
    text = (
        "from odoo.tools.mail import html_to_inner_content\n"
        "from odoo.tools.sql import create_index\n"
        "from odoo.tools.misc import street_split\n"
        "import odoo.tools.mail\n"
        "x = odoo.tools.mail.html_to_inner_content\n"
    )
    for step in ("migrate_170_180", "migrate_180_190"):
        assert _rewrite(step, text) == (text, [])
    new, reports = _rewrite("migrate_190_200", text)
    assert new == text.replace(
        "from odoo.tools.misc import street_split", "from odoo.tools.business_data import street_split")
    assert reports == []


# ---------------------------------------------------------------- 17.0 -> 18.0 / 18.0 -> 19.0


def test_18_star_exports_lost():
    new, reports = _rewrite("migrate_170_180", (
        "from odoo.tools import (\n"
        "    float_round,\n"
        "    html_to_inner_content,\n"
        "    Markup,\n"
        ")\n"
    ))
    assert new == (
        "from odoo.tools import float_round\n"
        "from odoo.tools.mail import html_to_inner_content\n"
        "from markupsafe import Markup\n"
    )
    assert reports == []


def test_19_explicit_exports_lost():
    new, reports = _rewrite("migrate_180_190", "from odoo.tools import image_process, date_range, config\n")
    assert new == (
        "from odoo.tools import config\n"
        "from odoo.tools.image import image_process\n"
        "from odoo.tools.date_utils import date_range\n"
    )
    assert reports == []


def test_one_line_compound_statement_reported():
    text = "try: from odoo.tools import Query\nexcept ImportError: pass\n"
    new, reports = _rewrite("migrate_190_200", text)
    assert new == text
    assert reports == [(1, "Query", "unchanged")]


def test_migrate_logs(tmp_path, caplog):
    module = tmp_path / "m"
    module.mkdir()
    path = module / "models.py"
    path.write_text("from odoo.tools import Query, convert_sql_import\n", encoding="utf-8")
    from odoo_module_migrate.migration_scripts.python_scripts.migrate_190_200 import (
        odoo_tools_imports as step,
    )

    with caplog.at_level(logging.INFO):
        step.migrate_odoo_tools_imports(tools=tools, logger=logging.getLogger("t"), module_path=module)
    assert path.read_text(encoding="utf-8") == (
        "from odoo.tools import convert_sql_import\nfrom odoo.models import Query\n"
    )
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "'convert_sql_import' cannot be imported from odoo.tools anymore" in errors[0]
    assert "ec785ba75827" in errors[0] and errors[0].endswith(f"File {path}:1")
