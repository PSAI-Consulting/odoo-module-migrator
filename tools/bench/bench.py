#!/usr/bin/env python3
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Migration bench: export modules, migrate them, install them on Odoo.

    python tools/bench/bench.py tools/bench/benches/example_oca_17_20.yaml --work D:/tmp/bench

The YAML file describes the bench (see tools/bench/benches/*.yaml):

    name: client_17_20
    from: "17.0"
    to: "20.0"
    odoo_root: D:/Odoo/odoo/20.0
    odoo_python: D:/.../venv/Scripts/python.exe
    db_config: D:/.../odoo20.conf        # database access only
    blank_template: migrator_bench_blank_20
    sources:
      - path: D:/Odoo/local-addons/client/addons   # a folder...
        modules: [my_module, sale_order_type]
      - git: D:/Odoo/local-addons/OdooOCA/sale-workflow  # ...or a git branch
        ref: origin/17.0
        modules: auto          # modules whose dependencies are available
        limit: 10

Steps (each one is skipped with --skip-*):
1. export the modules in <work>/<name>/addons (a git branch is read with
   ``git archive``: the repository is not touched);
2. migrate them (odoo_module_migrate, with --odoo-root and --report-dir);
3. static checks (tools/bench/check_modules.py);
4. install them one by one on a copy of a blank Odoo database
   (tools/bench/bench_install.py);
5. write <work>/<name>/RESULTS.md and results.json.
"""

import argparse
import ast
import io
import json
import pathlib
import queue
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

import yaml

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent  # repository root
sys.path.insert(0, str(HERE))

import bench_install as bi  # noqa: E402


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
    parser.add_argument("--retry-failed", action="store_true",
                        help="fast loop after a full run: re-migrate and re-install only the"
                             " FAILED modules (or --modules), each one on a fresh database")
    parser.add_argument("--modules", default="", help="with --retry-failed: comma separated")
    parser.add_argument("--blank", action="store_true",
                        help="with --retry-failed: start from the blank database (slower)"
                             " instead of the copy with the Odoo dependencies installed")
    args = parser.parse_args(argv)

    spec = yaml.safe_load(pathlib.Path(args.bench).read_text(encoding="utf-8"))
    work = pathlib.Path(args.work).resolve() / spec["name"]
    if args.retry_failed:
        retry_failed(spec, work, args.modules, args.workers, args.blank)
        return
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


def _source_of(spec, origin):
    for source in spec["sources"]:
        if origin in (source.get("git"), source.get("path")):
            return source
    raise SystemExit(f"source {origin} not in the bench file")


def _reference_closure(addons, reference, names):
    """Odoo modules (of the `reference` paths) needed by `names`, through the
    dependencies of the bench modules."""
    needed, seen, todo = set(), set(), list(names)
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        if (addons / name / "__manifest__.py").is_file():
            todo.extend(bi._manifest_of(addons, name).get("depends", []))
        elif any((pathlib.Path(p) / name / "__manifest__.py").is_file() for p in reference):
            needed.add(name)
    return needed


def ensure_deps_template(spec, options, env, reference, needed, tmp):
    """Copy of the blank database with the Odoo modules needed by the retried
    modules already installed: each test then installs only the module and its
    bench dependencies (Odoo start-up + standard modules are the slow part).
    Rebuilt when a needed module is missing. Returns its name."""
    name = f"{bi.PREFIX}deps_{spec['name']}"
    pg = lambda tool, *a, check=True: subprocess.run(  # noqa: E731
        [bi.pg_tool(options, tool), *bi.pg_args(options), *a], env=env, capture_output=True, check=check)
    if bi.database_exists(options, env, name):
        sql = "SELECT name FROM ir_module_module WHERE state = 'installed'"
        installed = set(pg("psql", "-d", name, "-tAc", sql).stdout.decode().split())
        if needed <= installed:
            return name
        pg("dropdb", "--if-exists", name, check=False)
    print(f"Creating {name} with {len(needed)} Odoo module(s)...", flush=True)
    pg("createdb", "-T", spec["blank_template"], name)
    conf = bi.write_conf(options, reference, name, tmp)
    proc = subprocess.run(
        [spec["odoo_python"], str(pathlib.Path(spec["odoo_root"]) / "odoo-bin"), "-c", str(conf),
         "-d", name, "-i", ",".join(sorted(needed)), "--stop-after-init", "--no-http",
         "--log-level=warn"],
        capture_output=True, env=dict(env, PYTHONUTF8="1"),
    )
    if proc.returncode != 0 or bi.FAILURE_RE.search((proc.stdout + proc.stderr).decode("utf-8", "replace")):
        pg("dropdb", "--if-exists", name, check=False)
        print("  failed: the blank database is used instead", flush=True)
        return spec["blank_template"]
    return name


def retry_failed(spec, work, modules, workers, blank):
    """Fast loop: re-export, re-migrate and re-install only the FAILED modules
    (or `modules`) of a previous full run, each one alone on a fresh copy of
    ``migrator_bench_deps_<name>`` (the blank database with the Odoo modules
    they need already installed; `blank`: from the blank database)."""
    addons = work / "addons"
    set_aside = work / "addons_set_aside"
    previous = json.loads((work / "results.json").read_text(encoding="utf-8"))
    by_module = {r["module"]: r for r in previous["modules"]}
    origin = json.loads((work / "origin.json").read_text(encoding="utf-8"))
    names = [m for m in modules.split(",") if m] or sorted(
        m for m, r in by_module.items() if r["status"] == "FAILED"
    )
    if not names:
        print("nothing to retry")
        return

    # 1. original code
    for name in names:
        for folder in (addons, set_aside):
            if (folder / name).exists():
                shutil.rmtree(folder / name)
        export(_source_of(spec, origin[name]), [name], addons)

    # 2. migration with the current code
    reports = work / "reports_retry"
    shutil.rmtree(reports, ignore_errors=True)
    run([sys.executable, "-m", "odoo_module_migrate", "-d", addons, "-m", ",".join(names),
               "-i", spec["from"], "-t", spec["to"], "-nc", "-npc",
               "--log-path", work / "migration_retry.log",
               "--odoo-root", spec["odoo_root"], "--odoo-python", spec["odoo_python"],
               "--report-dir", reports], cwd=ROOT, check=False)
    for name in names:
        if (reports / f"{name}.md").exists():
            shutil.copy(reports / f"{name}.md", work / "reports" / f"{name}.md")

    # 3. installation, each module alone on a blank database
    options = bi.read_config(spec["db_config"])
    env = bi.pg_env(options)
    odoo_root = pathlib.Path(spec["odoo_root"])
    reference = [str(odoo_root / "addons"), *[str(p) for p in _siblings(odoo_root)]]
    auto = [n for n in names if bi._manifest_of(addons, n).get("auto_install")]
    others = [n for n in names if n not in auto]
    results = {}
    with tempfile.TemporaryDirectory(prefix="odoo-retry-") as tmp:
        template = spec["blank_template"] if blank else ensure_deps_template(
            spec, options, env, reference, _reference_closure(addons, reference, names), tmp)

        def install(index, name):
            db = f"{bi.PREFIX}retry_{spec['name']}_w{index}"
            conf = bi.write_conf(options, [*reference, str(addons)], db, tmp)
            installer = bi.Installer(options, env, db, conf, odoo_root, spec["odoo_python"], addons)
            installer.create_from(template)
            try:
                start = time.time()
                # fresh copy per module: no checkpoint needed
                returncode, output = installer._odoo([name])
                ok = (returncode == 0 and not bi.FAILURE_RE.search(output)
                      and installer.states([name]).get(name) == "installed")
                status = "OK" if ok else "FAILED"
                result = {"module": name, "status": status, "seconds": round(time.time() - start, 1),
                          "error": "" if ok else bi.first_error(output),
                          "tail": "" if ok else "\n".join(output.splitlines()[-60:])}
            finally:
                installer.drop(db)
            print(f"{name:40} {status:7} {result['error'][:160]}", flush=True)
            return result

        # auto_install modules first and alone: a failing one would make every
        # other installation fail, it is set aside again
        for name in auto:
            results[name] = install(0, name)
            if results[name]["status"] != "OK":
                set_aside.mkdir(exist_ok=True)
                shutil.move(str(addons / name), str(set_aside / name))
        # one database per worker, never used by two installations at once
        free = queue.Queue()
        for index in range(workers):
            free.put(index)

        def run(name):
            index = free.get()
            try:
                return install(index, name)
            finally:
                free.put(index)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for result in pool.map(run, others):
                results[result["module"]] = result

    print("\nChanges:")
    for name in names:
        before, after = by_module.get(name, {}).get("status"), results[name]["status"]
        error_changed = before == after == "FAILED" and (
            by_module[name].get("error", "")[:100] != results[name]["error"][:100]
        )
        if before != after or error_changed:
            print(f"  {name}: {before} -> {after}  {results[name]['error'][:200]}")
    merged = [results.get(r["module"], r) for r in previous["modules"]]
    (work / "install.json").write_text(json.dumps(merged, indent=1), encoding="utf-8")
    write_results(work, spec, sorted(origin), merged)


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
