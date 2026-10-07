"""Exercise the shipped official scripts without an Odoo installation."""

import ast
import pytest

from odoo_module_migrate.upgrade_code import run_upgrade_code
from odoo_module_migrate.upgrade_code.bundled import options


@pytest.mark.parametrize("version", ["18.0", "19.0", "20.0"])
def test_offline_official_scripts(tmp_path, version):
    module = tmp_path / "sample"
    module.mkdir()
    manifest = module / "__manifest__.py"
    manifest.write_text(
        """{
    "name": "Café",
    "depends": ["base"],
    "data": [
        "views/before.xml",
        "security/ir.model.access.csv",
        "views/after.xml",
    ],
}
""",
        encoding="utf-8",
    )
    (module / "models.py").write_text(
        'from odoo import models, fields\nclass Sample(models.Model):\n    _name = "x.sample"\n    name = fields.Char()\n',
        encoding="utf-8",
    )
    (module / "views").mkdir()
    for name in ("before.xml", "after.xml"):
        (module / "views" / name).write_text("<odoo/>\n", encoding="utf-8")
    (module / "security").mkdir()
    (module / "security/ir.model.access.csv").write_text(
        "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\naccess_sample,Sample,model_x_sample,base.group_user,1,1,1,1\n"
    )
    result = run_upgrade_code(options(version), [module], "17.0", version)
    assert result.scripts
    assert not result.missing_modules
    assert not [(s["name"], s["error"]) for s in result.scripts if s["error"]]
    assert not [
        r
        for s in result.scripts
        for r in s["logs"]
        if r["level"] in {"ERROR", "CRITICAL"}
    ]
    if version == "20.0":
        data = ast.literal_eval(manifest.read_text(encoding="utf-8"))["data"]
        assert "security/ir.access.csv" in data
        assert "security/ir.model.access.csv" not in data
        assert data.index("views/before.xml") < data.index("views/after.xml")
        assert ",x.sample," in (module / "security/ir.access.csv").read_text()
