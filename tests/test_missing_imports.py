# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import logging

from odoo_module_migrate import tools
from odoo_module_migrate.migration_scripts.python_scripts.migrate_allways import (
    missing_imports as mi,
)


def test_missing_relative_imports(tmp_path, caplog):
    module = tmp_path / "my_mod"
    (module / "models").mkdir(parents=True)
    (module / "jobrunner").mkdir()
    (module / "__init__.py").write_text("from . import models, wizard\n", encoding="utf-8")
    (module / "models" / "__init__.py").write_text(
        "from . import partner\nfrom . import account_move\n", encoding="utf-8"
    )
    (module / "models" / "partner.py").write_text("x = 1\n", encoding="utf-8")
    (module / "jobrunner" / "__init__.py").write_text("queue_job_config = {}\n", encoding="utf-8")
    (module / "jobrunner" / "runner.py").write_text("from . import queue_job_config\n", encoding="utf-8")
    log = logging.getLogger("test_missing_imports")
    with caplog.at_level(logging.ERROR, logger="test_missing_imports"):
        mi.check_missing_relative_imports(tools=tools, logger=log, module_path=module)
    found = sorted(r.getMessage().split("'")[1] for r in caplog.records)
    # queue_job_config is a name of jobrunner/__init__.py: not reported
    assert found == ["account_move", "wizard"]
    # the misleading Python message is quoted, so that the install log error is found
    assert "partially initialized module" in caplog.records[0].getMessage()


def test_missing_models_package_python_message(tmp_path):
    # real case: the __init__.py of a module imports a
    # models package that does not exist (already broken in the source version)
    import subprocess
    import sys

    (tmp_path / "pkgx").mkdir()
    (tmp_path / "pkgx" / "__init__.py").write_text("from . import models\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", "import pkgx"], cwd=tmp_path, capture_output=True, text=True
    )
    assert "cannot import name 'models' from partially initialized module 'pkgx'" in result.stderr
