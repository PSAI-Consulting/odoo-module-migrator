#!/usr/bin/env python3
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Migration bench: export modules, migrate them, install them on Odoo.

    python tools/bench.py tools/benches/stof_17_20.yaml --work D:/tmp/bench

The YAML file describes the bench (see tools/benches/*.yaml):

    name: stof_17_20
    from: "17.0"
    to: "20.0"
    odoo_root: D:/Odoo/odoo/20.0
    odoo_python: D:/.../venv/Scripts/python.exe
    db_config: D:/.../odoo20.conf        # database access only
    blank_template: migrator_bench_blank_20
    sources:
      - path: D:/Odoo/local-addons/Stof/stof-20.0   # a folder...
        modules: [stof_partner_exchange, sale_order_type]
      - git: D:/Odoo/local-addons/OdooOCA/sale-workflow  # ...or a git branch
        ref: origin/17.0
        modules: auto          # modules whose dependencies are available
        limit: 10

Steps (each one is skipped with --skip-*):
1. export the modules in <work>/<name>/addons (a git branch is read with
   ``git archive``: the repository is not touched);
2. migrate them (odoo_module_migrate, with --odoo-root and --report-dir);
3. static checks (tools/check_modules.py);
4. install them one by one on a copy of a blank Odoo database
   (tools/bench_install.py);
5. write <work>/<name>/RESULTS.md and results.json.
"""

import argparse
import ast
import io
import json
import pathlib
import shutil
import subprocess
import sys
import zipfile

import yaml

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent


def _manifest(text):
    try:
        return ast.literal_eval(text.lstrip())
    except (ValueError, SyntaxError):
        return None


def git_modules(repo, ref):
    """{module: manifest dict} of the root folders of a git ref."""
    listing = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", ref],
        capture_output=True, check=True,
    ).stdout.decode("utf-8", "replace").splitlines()
    result = {}
    for path in listing:
        parts = path.split("/")
        if len(parts) == 2 and parts[1] == "__manifest__.py":
            text = subprocess.run(
                ["git", "-C", str(repo), "show", f"{ref}:{path}"], capture_output=True, check=True,
            ).stdout.decode("utf-8", "replace")
            manifest = _manifest(text)
            if manifest is not None:
                result[parts[0]] = manifest
    return result


def dir_modules(path):
    result = {}
    for manifest_path in pathlib.Path(path).glob("*/__manifest__.py"):
        manifest = _manifest(manifest_path.read_text(encoding="utf-8", errors="replace"))
        if manifest is not None:
            result[manifest_path.parent.name] = manifest
    return result


def reference_modules(odoo_source, version):
    """Modules of the Odoo SOURCE version (odoo + enterprise), from the bare repos."""
    names = set()
    for repo, prefix in ((odoo_source / "odoo.git", "addons/"), (odoo_source / "enterprise.git", "")):
        if not repo.exists():
            continue
        out = subprocess.run(
            ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", version],
            capture_output=True, check=False,
        ).stdout.decode("utf-8", "replace")
        for path in out.splitlines():
            if path.startswith(prefix) and path.endswith("/__manifest__.py"):
                rest = path[len(prefix):].split("/")
                if len(rest) == 2:
                    names.add(rest[0])
    return names | {"base"}


def select(available, wanted, reference, limit=None):
    """Explicit list, or 'auto': installable modules whose dependencies are
    all in Odoo or in the selection (dependencies are added)."""
    if wanted != "auto":
        selected = set(wanted)
        todo = list(wanted)
        while todo:  # add the dependencies found in the same source
            for dep in available.get(todo.pop(), {}).get("depends", []):
                if dep in available and dep not in selected:
                    selected.add(dep)
                    todo.append(dep)
        return sorted(selected)
    ok = {}

    def resolvable(name, stack=()):
        if name in ok:
            return ok[name]
        manifest = available.get(name)
        if manifest is None or not manifest.get("installable", True) or name in stack:
            ok[name] = False
            return False
        ok[name] = all(
            dep in reference or resolvable(dep, (*stack, name))
            for dep in manifest.get("depends", [])
        )
        return ok[name]

    names = sorted(n for n in available if resolvable(n))
    if limit:
        # the first `limit` modules, with their dependencies
        chosen = set()
        for name in names:
            if len(chosen) >= limit:
                break
            chosen |= {name, *[d for d in available[name].get("depends", []) if d in available]}
        names = sorted(chosen)
    return names


def export(source, names, target):
    if "git" in source:
        archive = subprocess.run(
            ["git", "-C", source["git"], "archive", "--format=zip", source["ref"], *names],
            capture_output=True, check=True,
        ).stdout
        zipfile.ZipFile(io.BytesIO(archive)).extractall(target)
    else:
        for name in names:
            shutil.copytree(pathlib.Path(source["path"]) / name, target / name)


def run(cmd, **kwargs):
    print("$ " + " ".join(map(str, cmd))[:300], flush=True)
    return subprocess.run([str(c) for c in cmd], **kwargs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bench", help="bench YAML file")
    parser.add_argument("--work", required=True, help="working directory")
    parser.add_argument("--repos", default="D:/Odoo/.repos", help="bare Odoo repositories")
    parser.add_argument("--skip-migration", action="store_true")
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--workers", type=int, default=3, help="parallel installations")
    args = parser.parse_args(argv)

    spec = yaml.safe_load(pathlib.Path(args.bench).read_text(encoding="utf-8"))
    work = pathlib.Path(args.work).resolve() / spec["name"]
    addons = work / "addons"
    python = sys.executable

    if not args.skip_migration:
        if work.exists():
            shutil.rmtree(work)
        addons.mkdir(parents=True)
        reference = reference_modules(pathlib.Path(args.repos), spec["from"])
        origin = {}
        for source in spec["sources"]:
            available = (
                git_modules(source["git"], source["ref"]) if "git" in source
                else dir_modules(source["path"])
            )
            names = [n for n in select(available, source.get("modules", "auto"), reference,
                                       source.get("limit")) if n not in origin]
            export(source, names, addons)
            origin.update({n: source.get("git") or source.get("path") for n in names})
            print(f"{len(names)} module(s) from {source.get('git') or source.get('path')}")
        (work / "origin.json").write_text(json.dumps(origin, indent=1), encoding="utf-8")
        modules = sorted(origin)
        run([python, "-m", "odoo_module_migrate", "-d", addons, "-m", ",".join(modules),
             "-i", spec["from"], "-t", spec["to"], "-nc", "-npc",
             "--log-path", work / "migration.log",
             "--odoo-root", spec["odoo_root"], "--odoo-python", spec["odoo_python"],
             "--report-dir", work / "reports"], cwd=ROOT, check=False)
    modules = sorted(json.loads((work / "origin.json").read_text(encoding="utf-8")))

    check = run([python, HERE / "check_modules.py", addons, "--modules", ",".join(modules),
                 "--addons-path", ",".join(
                     str(pathlib.Path(spec["odoo_root"]) / p) for p in ("addons", "odoo/addons"))
                 + "," + ",".join(str(p) for p in _siblings(spec["odoo_root"]))],
                capture_output=True, check=False)
    (work / "check.txt").write_bytes(check.stdout)

    install = []
    if not args.skip_install:
        # modules with errors in their migration report will probably fail:
        # installed alone so that they do not make a whole batch fail
        isolate = [m for m in modules if (_report_summary(work, m)[2] or "0") != "0"]
        run([python, HERE / "bench_install.py", addons,
             "--config", spec["db_config"], "--blank-template", spec["blank_template"],
             "--odoo-root", spec["odoo_root"], "--odoo-python", spec["odoo_python"],
             "--modules", ",".join(modules), "--name", spec["name"],
             "--isolate", ",".join(isolate), "--workers", str(args.workers),
             "--output", work / "install.json"], check=False)
        install = json.loads((work / "install.json").read_text(encoding="utf-8"))
    write_results(work, spec, modules, install)


def _siblings(odoo_root):
    root = pathlib.Path(odoo_root)
    return [p for p in (root.parent.parent / r / root.name for r in ("enterprise", "design-themes"))
            if p.is_dir()]


def _report_summary(work, module):
    path = work / "reports" / f"{module}.md"
    if not path.exists():
        return "", "", ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("| **"):
            cells = [c.strip(" *") for c in line.strip("|").split("|")]
            return cells[0], cells[1], cells[2]
    return "", "", ""


def write_results(work, spec, modules, install):
    by_module = {r["module"]: r for r in install}
    origin = json.loads((work / "origin.json").read_text(encoding="utf-8"))
    ok = sum(r["status"] == "OK" for r in install)
    blocked = sum(r["status"] == "BLOCKED" for r in install)
    lines = [
        f"# Banc {spec['name']} : {spec['from']} → {spec['to']}",
        "",
        f"**{ok} / {len(install) or len(modules)}** modules installés sur une base Odoo"
        f" {spec['to']} vierge ({blocked} bloqués par une dépendance en échec).",
        "",
        "| Module | Origine | Installation | Risque (rapport) | TODO | Erreurs | Première erreur |",
        "|---|---|---|---|---|---|---|",
    ]
    for module in modules:
        result = by_module.get(module, {})
        risk, todo, errors = _report_summary(work, module)
        error = result.get("error", "").replace("|", "/")[:140]
        lines.append(
            f"| [{module}](reports/{module}.md) | {pathlib.Path(origin[module]).name} |"
            f" {result.get('status', '-')} | {risk} | {todo} | {errors} | {error} |"
        )
    (work / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (work / "results.json").write_text(json.dumps({
        "name": spec["name"], "installed": ok, "total": len(install), "blocked": blocked,
        "modules": install,
    }, indent=1), encoding="utf-8")
    print(f"\n{ok}/{len(install)} installed -> {work / 'RESULTS.md'}")


if __name__ == "__main__":
    main()
