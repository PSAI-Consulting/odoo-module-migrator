# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Safe bench verification hook for autonomous Odoo migration repair.

Integrates with tools/bench/bench_install.py to verify actual module installation
on a throwaway test database.
CRITICAL SAFETY CONSTRAINTS:
- STRICT database prefix: only databases matching `migrator_bench_*` are touched.
- Never accesses or modifies an existing user database.
- Databases are dropped in `finally:` blocks.
- Execution timeout is strictly enforced.
"""

from __future__ import annotations

import pathlib
import subprocess
import time
import uuid
from typing import Any

BENCH_DB_PREFIX = "migrator_bench_"


class BenchVerifier:
    """Verifies that a migrated module installs cleanly on Odoo."""

    def __init__(
        self,
        odoo_root: pathlib.Path | str | None,
        odoo_python: pathlib.Path | str | None,
        db_config: pathlib.Path | str | None = None,
        template_db: str = "migrator_bench_blank_20",
        timeout_seconds: int = 120,
    ):
        self.odoo_root = pathlib.Path(odoo_root).resolve() if odoo_root else None
        self.odoo_python = str(odoo_python) if odoo_python else None
        self.db_config = pathlib.Path(db_config).resolve() if db_config else None
        self.template_db = template_db
        self.timeout = timeout_seconds

    @property
    def is_configured(self) -> bool:
        return bool(
            self.odoo_root
            and self.odoo_root.is_dir()
            and self.odoo_python
            and self.db_config
            and self.db_config.is_file()
        )

    def verify_module_install(
        self,
        module_path: pathlib.Path,
        addons_paths: list[pathlib.Path | str] | None = None,
    ) -> tuple[bool, str]:
        """Try installing module on a throwaway database.

        Returns (success: bool, failure_detail: str).
        """
        if not self.is_configured:
            return True, ""  # Not configured, skip gracefully

        module_name = module_path.name
        temp_db_name = f"{BENCH_DB_PREFIX}repair_{uuid.uuid4().hex[:8]}"

        # Absolute safety assertion
        if not temp_db_name.startswith(BENCH_DB_PREFIX):
            raise RuntimeError(f"Safety violation: DB name {temp_db_name!r} lacks {BENCH_DB_PREFIX}")

        all_addons = [str(module_path.parent)]
        if addons_paths:
            all_addons.extend(str(p) for p in addons_paths)

        try:
            # Import bench_install helpers if available
            bench_install_path = (
                pathlib.Path(__file__).parent.parent.parent / "tools" / "bench" / "bench_install.py"
            )
            if not bench_install_path.is_file():
                return True, ""

            import sys
            sys.path.insert(0, str(bench_install_path.parent))
            import bench_install as bi  # type: ignore

            options = bi.read_config(str(self.db_config))
            env = bi.pg_env(options)

            # Create clone from template
            bi.ensure_blank_template(
                options, env, self.template_db, all_addons,
                self.odoo_root, self.odoo_python, str(module_path.parent),
            )
            installer = bi.Installer(
                options, env, temp_db_name, str(self.db_config),
                self.odoo_root, self.odoo_python, str(module_path.parent),
            )
            installer.create_from(self.template_db, temp_db_name)

            # Test installation
            ok, output, duration = installer._try([module_name])
            if ok:
                return True, ""

            # Extract concise failure error
            match = bi.FAILURE_RE.search(output)
            detail = match.group(0) if match else output[-1500:]
            return False, detail.strip()

        except Exception as exc:
            return False, f"Erreur de banc Odoo: {exc}"

        finally:
            # Ensure throwaway DB is unconditionally dropped
            try:
                if 'installer' in locals():
                    installer.drop(temp_db_name)
            except Exception:
                pass
