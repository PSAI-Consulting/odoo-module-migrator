# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""odoo.registry() -> odoo.modules.registry.Registry (18 -> 19)."""

import logging
import os

from odoo_module_migrate.migration_scripts.python_scripts.migrate_180_190 import (
    odoo_registry as orr,
)


def _check(text, expected, reported=()):
    new, rep = orr._rewrite(text)
    assert new == expected
    assert [line for line, _w in rep] == list(reported)
    # idempotent
    assert orr._rewrite(new)[0] == new
    return rep


# Stof edi_platform / sale_order_block_duplicate_product
STOF = '''from odoo import registry, models, fields, api, _


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    def set_values(self):
        with registry(self.env.cr.dbname).cursor() as new_cr:
            new_cr.execute("SELECT 1")
'''


def test_from_import_with_other_names():
    _check(STOF, STOF.replace(
        "from odoo import registry, models, fields, api, _",
        "from odoo import models, fields, api, _\nfrom odoo.modules.registry import Registry",
    ).replace("with registry(", "with Registry("))


def test_from_import_alone_and_alias():
    text = "from odoo import registry as reg\n\n\ndef run(db):\n    return reg(db)\n"
    _check(text, "from odoo.modules.registry import Registry\n\n\ndef run(db):\n    return Registry(db)\n")


def test_unused_import_dropped():
    # Stof stof_api_transport: imported, never used
    text = "from odoo import registry, models\n\n\nclass A(models.Model):\n    _name = 'a'\n"
    _check(text, "from odoo import models\n\n\nclass A(models.Model):\n    _name = 'a'\n")
    text = "from odoo import registry\nfrom odoo import models\n"
    _check(text, "from odoo import models\n")


def test_keyword_argument():
    text = "from odoo import registry\nx = registry(database_name=db)\n"
    _check(text, "from odoo.modules.registry import Registry\nx = Registry(db)\n")


def test_odoo_attribute():
    text = "import odoo\n\n\ndef run(db):\n    with odoo.registry(db).cursor() as cr:\n        pass\n"
    _check(text, (
        "import odoo\nfrom odoo.modules.registry import Registry\n\n\n"
        "def run(db):\n    with Registry(db).cursor() as cr:\n        pass\n"
    ))
    # Stof stof_custom_atp_reservation: comment kept on its line
    text = "import odoo  # noqa: E402\nr = odoo.registry(db_name)\n"
    _check(text, "import odoo  # noqa: E402\nfrom odoo.modules.registry import Registry\nr = Registry(db_name)\n")
    # Registry already imported: not added twice
    text = "import odoo\nfrom odoo.modules.registry import Registry\nr = odoo.registry(db)\n"
    _check(text, "import odoo\nfrom odoo.modules.registry import Registry\nr = Registry(db)\n")


def test_without_argument_reported_and_untouched():
    text = "from odoo import registry\n\n\ndef run():\n    return registry()\n"
    rep = _check(text, text, [5])
    assert "registry" in rep[0][1]
    # one call without argument: the other one is not converted either
    text = "from odoo import registry\na = registry(db)\nb = registry()\nc = registry\n"
    _check(text, text, [3, 4])
    text = "import odoo\na = odoo.registry(db)\nb = odoo.registry()\n"
    _check(text, "import odoo\nfrom odoo.modules.registry import Registry\na = Registry(db)\nb = odoo.registry()\n", [3])


def test_other_registry_names_untouched():
    text = '''from odoo import api, models


def post_init(cr, registry):
    registry(cr.dbname)


class A(models.Model):
    _name = "a"

    def f(self):
        registry = self.env.registry
        registry.clear_cache()
        return self.env.registry(x), self.registry(y)
'''
    _check(text, text)
    # imported but shadowed by a parameter: only the global use is converted
    text = ("from odoo import registry\n\n\ndef hook(cr, registry):\n    registry(cr)\n\n\n"
            "def run(db):\n    registry(db)\n    [registry(x) for registry in y]\n")
    _check(text, (
        "from odoo.modules.registry import Registry\n\n\ndef hook(cr, registry):\n    registry(cr)\n\n\n"
        "def run(db):\n    Registry(db)\n    [registry(x) for registry in y]\n"
    ))
    # odoo not imported, or odoo.modules.registry: untouched
    for text in ("x = odoo.registry(db)\n",
                 "import odoo\nx = odoo.modules.registry.Registry(db)\n",
                 "from odoo.modules import registry\nx = registry.Registry(db)\n"):
        _check(text, text)


def test_registry_name_conflict_and_rebound():
    text = "from odoo import registry\nfrom foo import Registry\nx = registry(db)\n"
    _check(text, text, [3])
    text = "from odoo import registry\nregistry = 3\nx = registry(db)\n"
    _check(text, text, [1])


def test_nested_import_reported():
    text = "def run(db):\n    from odoo import registry\n    return registry(db)\n"
    _check(text, text, [2])


def test_old_regex_removed():
    # converted code must not be reported anymore by the 17 -> 18 text errors
    assert not os.path.exists(
        "odoo_module_migrate/migration_scripts/text_errors/migrate_170_180/registry.yaml"
    )


def test_migrate_function(tmp_path, caplog):
    from odoo_module_migrate import tools

    path = tmp_path / "models" / "a.py"
    path.parent.mkdir()
    path.write_text(STOF + "\n\ndef bad():\n    return 1\n", encoding="utf-8")
    other = tmp_path / "models" / "b.py"
    other.write_text("import odoo\nx = odoo.registry()\n", encoding="utf-8")
    logger = logging.getLogger("test_registry")
    with caplog.at_level(logging.INFO, logger="test_registry"):
        orr.migrate_odoo_registry(tools=tools, logger=logger, module_path=tmp_path)
    assert "with Registry(self.env.cr.dbname)" in path.read_text(encoding="utf-8")
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1 and errors[0].endswith("b.py:2")
