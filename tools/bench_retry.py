#!/usr/bin/env python3
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Fast loop on the failures of a bench: re-migrate and re-install only them.

    python tools/bench_retry.py tools/benches/stof_17_20.yaml --work D:/tmp/bench
    python tools/bench_retry.py ... --modules stof_product,easi_tax

After a full run of tools/bench.py, the FAILED modules (or --modules) are:
1. exported again from their source (the original code) into the bench copy;
2. migrated again with the current code of the migrator (their reports are
   updated in <work>/<name>/reports);
3. installed each one alone, in parallel, on a fresh copy of
   ``migrator_bench_deps_<name>``: the blank database with the Odoo modules
   they need already installed (built once, rebuilt when a module is
   missing; --blank to start from the blank database). Odoo installs their
   bench dependencies, already migrated by the full run. A fresh copy per
   module: what another test installed or broke never changes the result.

The results replace those of the modules in results.json / RESULTS.md, and the
changes of status are printed. Modules BLOCKED by a dependency are not retried:
re-run the full bench when their dependency installs.
"""

import argparse
import json
import queue
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

import yaml

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import bench  # noqa: E402
import bench_install as bi  # noqa: E402


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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bench", help="bench YAML file")
    parser.add_argument("--work", required=True, help="working directory of the full run")
    parser.add_argument("--modules", default="", help="comma separated (default: the FAILED ones)")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--blank", action="store_true",
                        help="install on the blank database (slower), not on the copy"
                             " with the Odoo dependencies already installed")
    args = parser.parse_args(argv)

    spec = yaml.safe_load(pathlib.Path(args.bench).read_text(encoding="utf-8"))
    work = pathlib.Path(args.work).resolve() / spec["name"]
    addons = work / "addons"
    set_aside = work / "addons_set_aside"
    previous = json.loads((work / "results.json").read_text(encoding="utf-8"))
    by_module = {r["module"]: r for r in previous["modules"]}
    origin = json.loads((work / "origin.json").read_text(encoding="utf-8"))
    names = [m for m in args.modules.split(",") if m] or sorted(
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
        bench.export(_source_of(spec, origin[name]), [name], addons)

    # 2. migration with the current code
    reports = work / "reports_retry"
    shutil.rmtree(reports, ignore_errors=True)
    bench.run([sys.executable, "-m", "odoo_module_migrate", "-d", addons, "-m", ",".join(names),
               "-i", spec["from"], "-t", spec["to"], "-nc", "-npc",
               "--log-path", work / "migration_retry.log",
               "--odoo-root", spec["odoo_root"], "--odoo-python", spec["odoo_python"],
               "--report-dir", reports], cwd=bench.ROOT, check=False)
    for name in names:
        if (reports / f"{name}.md").exists():
            shutil.copy(reports / f"{name}.md", work / "reports" / f"{name}.md")

    # 3. installation, each module alone on a blank database
    options = bi.read_config(spec["db_config"])
    env = bi.pg_env(options)
    odoo_root = pathlib.Path(spec["odoo_root"])
    reference = [str(odoo_root / "addons"), *[str(p) for p in bench._siblings(odoo_root)]]
    auto = [n for n in names if bi._manifest_of(addons, n).get("auto_install")]
    others = [n for n in names if n not in auto]
    results = {}
    with tempfile.TemporaryDirectory(prefix="odoo-retry-") as tmp:
        template = spec["blank_template"] if args.blank else ensure_deps_template(
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
        for index in range(args.workers):
            free.put(index)

        def run(name):
            index = free.get()
            try:
                return install(index, name)
            finally:
                free.put(index)

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
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
    bench.write_results(work, spec, sorted(origin), merged)


if __name__ == "__main__":
    main()
