# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from odoo_module_migrate.analysis import imports


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_removed_names(tmp_path):
    """OPERATORS of stock/models/product.py was removed in 19.0 (odoo
    92301a5b300d): importing it prevents the module from loading."""
    ref = tmp_path / "odoo"
    _write(ref / "stock" / "__manifest__.py", "{'name': 'stock'}")
    _write(ref / "stock" / "models" / "__init__.py", "from . import product\n")
    _write(ref / "stock" / "models" / "product.py",
           "from odoo import models\nimport logging as log\nif True:\n    COND = 1\n"
           "class ProductProduct(models.Model):\n    pass\n")
    _write(ref / "lazy" / "__manifest__.py", "{'name': 'lazy'}")
    _write(ref / "lazy" / "tools.py", "from .other import *\n")
    mod = tmp_path / "custom" / "my_mod"
    _write(mod / "__manifest__.py", "{'name': 'my_mod'}")
    _write(mod / "models" / "a.py", (
        "from odoo.addons.stock.models.product import OPERATORS, ProductProduct, log, COND\n"
        "from odoo.addons.stock.models import product\n"
        "from odoo.addons.stock.models.gone import X\n"
        "from odoo.addons.lazy.tools import anything\n"
        "from odoo.addons.other_custom.models import Y\n"
    ))
    # tests are not loaded at installation
    _write(mod / "tests" / "test_a.py", "from odoo.addons.stock.models.product import OPERATORS\n")
    index = imports.ImportIndex([ref])
    found = sorted((line, msg) for _p, line, msg in imports.check_module(mod, index))
    assert [line for line, _m in found] == [1, 3], found
    assert "'OPERATORS' is not defined in odoo.addons.stock.models.product" in found[0][1]
    assert "odoo.addons.stock.models.gone does not exist" in found[1][1]
