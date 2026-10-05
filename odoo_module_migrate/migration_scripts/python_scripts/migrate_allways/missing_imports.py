# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Relative imports of files that do not exist (the module cannot load).

    from . import models        # but there is no models.py / models/
    from .models import partner # but there is no models/partner.py

This is a defect of the original code (it does not come from the
migration): it is reported so that the failure is understood before the
installation ("cannot import name ... from partially initialized module").
"""

import ast


def _exists(directory, name):
    return (directory / f"{name}.py").is_file() or (directory / name).is_dir()


def check_missing_relative_imports(**kwargs):
    tools, logger = kwargs["tools"], kwargs["logger"]
    for path in tools.get_files(kwargs["module_path"], (".py",)):
        if "static" in path.parts:
            continue
        try:
            tree = ast.parse(tools._read_content(path))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.ImportFrom) or node.level != 1:
                continue
            base = path.parent
            if node.module:  # from .models import x / from .models.sub import x
                parts = node.module.split(".")
                missing = None
                for part in parts:
                    if not _exists(base, part):
                        missing = part
                        break
                    base = base / part
                names = [] if missing else [
                    a.name for a in node.names
                    if (base).is_dir() and a.name != "*" and not _exists(base, a.name)
                    and not _defines(base / "__init__.py", a.name)
                ]
                missing = [missing] if missing else names
            else:  # from . import models, wizard (a file, or a name of __init__.py)
                missing = [
                    a.name for a in node.names
                    if not _exists(base, a.name) and not _defines(base / "__init__.py", a.name)
                ]
            for name in missing:
                logger.error(
                    "Import of '%s' that does not exist in the module: the module cannot load"
                    " (defect of the original code, not of the migration). File %s:%s"
                    % (name, path, node.lineno)
                )


def _defines(init_path, name):
    """Whether a package __init__.py defines `name` (class, function, import)."""
    if not init_path.is_file():
        return False
    try:
        tree = ast.parse(init_path.read_bytes())
    except SyntaxError:
        return True  # unknown: no report
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
            return True
        # "from . import x" imports the submodule x: it does not define it
        if isinstance(node, ast.ImportFrom) and node.level >= 1 and not node.module:
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)) and any(
            (a.asname or a.name.split(".")[0]) == name for a in node.names
        ):
            return True
        if isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, ast.Store):
            return True
    return False
