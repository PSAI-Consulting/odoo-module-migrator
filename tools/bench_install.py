#!/usr/bin/env python3
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Install migrated modules on a throw-away copy of a blank Odoo database.

    python tools/bench_install.py <modules_dir> --config odoo20.conf \\
        --template STOF-20-VIERGE --odoo-root D:/Odoo/odoo/20.0 \\
        --odoo-python D:/.../venv/Scripts/python.exe --name after

* the database ``migrator_bench_<name>`` is created with
  ``createdb -T <template>`` (the template is never modified, its C collation
  is inherited: Odoo never creates the database itself) and dropped at the end
  (--keep-db to keep it). Only ``migrator_bench_*`` databases are ever dropped;
* modules are installed one by one, dependencies first, each with
  ``--stop-after-init``: a failing module does not stop the others;
* the result (JSON + table) gives, per module, OK / FAILED and the first error.
"""

import argparse
import ast
import configparser
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time

PREFIX = "migrator_bench_"


def read_config(path):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    return dict(parser["options"])


def pg_env(options):
    env = dict(os.environ)
    if options.get("db_password"):
        env["PGPASSWORD"] = options["db_password"]
    return env


def pg_args(options):
    args = []
    for opt, key in (("-h", "db_host"), ("-p", "db_port"), ("-U", "db_user")):
        if options.get(key) and options[key] != "False":
            args += [opt, options[key]]
    return args


def pg_tool(options, name):
    bindir = options.get("pg_path")
    if bindir and bindir != "False":
        return str(pathlib.Path(bindir) / name)
    return name


def write_conf(options, addons_path, db, tmp):
    conf = pathlib.Path(tmp) / f"{db}.conf"
    bench = configparser.ConfigParser(interpolation=None)
    bench["options"] = {
        k: v for k, v in options.items()
        if k.startswith("db_") and k != "db_name" or k == "pg_path"
    }
    bench["options"].update({
        "addons_path": ",".join(addons_path),
        "data_dir": str(pathlib.Path(tmp) / "data"),
        "db_name": db,
        "dbfilter": f"^{db}$",
        "list_db": "False",
        "max_cron_threads": "0",
    })
    with conf.open("w", encoding="utf-8") as f:
        bench.write(f)
    return conf


def database_exists(options, env, name):
    out = subprocess.run(
        [pg_tool(options, "psql"), *pg_args(options), "-d", "postgres", "-tAc",
         f"SELECT 1 FROM pg_database WHERE datname = '{name}'"],
        env=env, capture_output=True, check=True,
    ).stdout
    return out.strip() == b"1"


def ensure_blank_template(options, env, name, addons, odoo_root, odoo_python, tmp):
    """A blank database (base only). Created by hand in C collation: Odoo must
    never create the database itself (PostgreSQL 18 on Windows)."""
    if database_exists(options, env, name):
        return
    print(f"Creating the blank database {name} (base only)...", flush=True)
    subprocess.run(
        [pg_tool(options, "createdb"), *pg_args(options), "-T", "template0", "-E", "UTF8",
         "--lc-collate", "C", "--lc-ctype", "C", name],
        env=env, check=True, capture_output=True,
    )
    conf = write_conf(options, addons, name, tmp)
    proc = subprocess.run(
        [odoo_python, str(odoo_root / "odoo-bin"), "-c", str(conf), "-d", name,
         "-i", "base", "--stop-after-init", "--no-http", "--log-level=warn"],
        capture_output=True, env=dict(env, PYTHONUTF8="1"),
    )
    if proc.returncode != 0:
        subprocess.run([pg_tool(options, "dropdb"), *pg_args(options), "--if-exists", name],
                       env=env, capture_output=True)
        raise SystemExit(
            "Blank database not initialized:\n"
            + (proc.stdout + proc.stderr).decode("utf-8", "replace")[-3000:]
        )


FAILURE_RE = re.compile(
    r" (ERROR|CRITICAL) .*(Failed to load|Failed to initialize|"
    r"Some modules have inconsistent states|Traceback)|^Traceback",
    re.M,
)


class Installer:
    """Install modules by batches on a database, with checkpoints.

    A batch is installed by one Odoo run (Odoo start-up is the slow part).
    If it fails, the database is restored from the checkpoint taken before the
    batch, and the batch is split in two: a module that fails alone is a real
    failure, with its own error. The result of a run is read in the database
    (ir_module_module.state), not guessed from the log.
    """

    def __init__(self, options, env, db, conf, odoo_root, odoo_python, directory):
        self.options, self.env, self.db, self.conf = options, env, db, conf
        self.odoo_root, self.odoo_python, self.directory = odoo_root, odoo_python, directory
        self.checkpoint = db + "_ckpt"
        self.depends, self.installable = {}, {}

    # -- database helpers
    def _pg(self, tool, *args, check=True):
        return subprocess.run([pg_tool(self.options, tool), *pg_args(self.options), *args],
                              env=self.env, capture_output=True, check=check)

    def drop(self, name):
        self._pg("dropdb", "--if-exists", name, check=False)

    def create_from(self, template, name=None):
        name = name or self.db
        self.drop(name)
        self._pg("createdb", "-T", template, name)

    def states(self, names):
        sql = "SELECT name, state FROM ir_module_module WHERE name IN (%s)" % ",".join(
            "'%s'" % n.replace("'", "") for n in names
        )
        out = self._pg("psql", "-d", self.db, "-tAc", sql).stdout.decode("utf-8", "replace")
        return dict(line.split("|", 1) for line in out.splitlines() if "|" in line)

    # -- installation
    def _odoo(self, names):
        proc = subprocess.run(
            [self.odoo_python, str(self.odoo_root / "odoo-bin"), "-c", str(self.conf),
             "-d", self.db, "-i", ",".join(names), "--stop-after-init", "--no-http",
             "--log-level=warn"],
            capture_output=True, env=dict(self.env, PYTHONUTF8="1"),
        )
        return proc.returncode, (proc.stdout + proc.stderr).decode("utf-8", "replace")

    def _try(self, names):
        """Install `names` from the current state; restore it on failure."""
        self.create_from(self.db, self.checkpoint)
        start = time.time()
        returncode, output = self._odoo(names)
        states = self.states(names)
        ok = returncode == 0 and not FAILURE_RE.search(output) and all(
            states.get(n) == "installed" for n in names
        )
        if not ok:
            self.create_from(self.checkpoint)  # back to the state before the batch
        return ok, output, round(time.time() - start, 1)

    def _install(self, batch, results, failed):
        batch = [n for n in batch if not self._blocked(n, results, failed)]
        if not batch:
            return
        ok, output, seconds = self._try(batch)
        if ok:
            for name in batch:
                self._record(results, name, "OK", seconds / len(batch))
        elif len(batch) == 1:
            failed.add(batch[0])
            self._record(results, batch[0], "FAILED", seconds, output)
        else:
            middle = len(batch) // 2
            self._install(batch[:middle], results, failed)
            self._install(batch[middle:], results, failed)

    def _blocked(self, name, results, failed):
        if not self.installable.get(name, True):
            self._record(results, name, "SKIPPED", 0, error="'installable': False in the manifest")
            return True
        blocking = [d for d in self.depends.get(name, []) if d in failed]
        if blocking:
            failed.add(name)
            self._record(results, name, "BLOCKED", 0, error="dependency failed: " + ", ".join(blocking))
            return True
        return False

    @staticmethod
    def _record(results, name, status, seconds, output="", error=""):
        results.append({
            "module": name, "status": status, "seconds": round(seconds, 1),
            "error": error or (first_error(output) if status == "FAILED" else ""),
            "tail": "\n".join(output.splitlines()[-60:]) if status == "FAILED" else "",
        })
        print(f"{name:40} {status:7} {results[-1]['error'][:160]}", flush=True)

    def run(self, order, batch_size, isolate=()):
        """`isolate`: modules likely to fail (errors in their migration
        report): installed alone, so that they do not make a batch fail."""
        for name in order:
            manifest = ast.literal_eval(
                (self.directory / name / "__manifest__.py").read_text(encoding="utf-8").lstrip()
            )
            self.depends[name] = manifest.get("depends", [])
            self.installable[name] = manifest.get("installable", True)
        results, failed = [], set()
        batch = []
        for name in order:
            # a batch never contains a module and one of its dependencies of
            # the same batch: if the dependency fails, the module is BLOCKED
            if batch and (
                len(batch) >= batch_size or name in isolate
                or set(self.depends[name]) & set(batch)
            ):
                self._install(batch, results, failed)
                batch = []
            if name in isolate:
                self._install([name], results, failed)
                continue
            batch.append(name)
        if batch:
            self._install(batch, results, failed)
        return results


def split_independent(order, depends, workers):
    """Groups of modules without dependency between groups (connected
    components of the dependency graph), balanced on `workers` groups."""
    parent = {name: name for name in order}

    def find(name):
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    for name in order:
        for dep in depends.get(name, []):
            if dep in parent:
                parent[find(name)] = find(dep)
    components = {}
    for name in order:
        components.setdefault(find(name), []).append(name)
    groups = [[] for _ in range(max(1, workers))]
    for component in sorted(components.values(), key=len, reverse=True):
        min(groups, key=len).extend(component)
    position = {name: i for i, name in enumerate(order)}
    return [sorted(g, key=position.get) for g in groups if g]


def topological(directory, names):
    manifests = {
        n: ast.literal_eval((directory / n / "__manifest__.py").read_text(encoding="utf-8").lstrip())
        for n in names
    }
    done, order = set(), []

    def visit(name, stack=()):
        if name in done or name not in manifests or name in stack:
            return
        for dep in manifests[name].get("depends", []):
            visit(dep, (*stack, name))
        done.add(name)
        order.append(name)

    for name in sorted(names):
        visit(name)
    return order


ERROR_RE = re.compile(
    r"^(?:\S+ \S+ \d+ (?:ERROR|CRITICAL) .*|.*(?:Error|Exception|ParseError)\b.*)$", re.M
)


def first_error(output):
    """Most useful line of the failure: the message of a ParseError (on the
    lines after 'while parsing <file>'), else the last 'XxxError: ...' line."""
    lines = output.splitlines()
    for i, line in enumerate(lines):
        if "ParseError" in line and "while parsing" in line:
            detail = " ".join(l.strip() for l in lines[i + 1:i + 4] if l.strip())
            source = line.rsplit("/", 1)[-1]
            return f"ParseError {source}: {detail}"[:600]
    for line in reversed(lines):
        if re.match(r"^\s*[\w.]+(?:Error|Exception)\b", line):
            return line.strip()[:600]
    found = [m.group(0) for m in ERROR_RE.finditer(output)]
    return (found[0] if found else lines[-1] if lines else "").strip()[:600]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory")
    parser.add_argument("--config", required=True, help="Odoo config of the target (db access)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--template", help="existing blank database to copy")
    group.add_argument(
        "--blank-template",
        help=f"name of a blank database ({PREFIX}*) created if needed: C collation, "
             "base module only, then copied for each run",
    )
    parser.add_argument("--odoo-root", required=True)
    parser.add_argument("--odoo-python", required=True)
    parser.add_argument("--addons-path", default="", help="reference addons (default: from --odoo-root)")
    parser.add_argument("--modules", default="", help="comma separated (default: all)")
    parser.add_argument("--name", default="run")
    parser.add_argument("--batch-size", type=int, default=12,
                        help="modules installed by one Odoo run (1 = one by one)")
    parser.add_argument("--isolate", default="",
                        help="modules installed alone (likely to fail), comma separated")
    parser.add_argument("--workers", type=int, default=3,
                        help="independent groups of modules installed in parallel")
    parser.add_argument("--keep-db", action="store_true")
    parser.add_argument("--output", help="JSON result file")
    args = parser.parse_args(argv)

    directory = pathlib.Path(args.directory).resolve()
    odoo_root = pathlib.Path(args.odoo_root).resolve()
    options = read_config(args.config)
    env = pg_env(options)
    db = PREFIX + re.sub(r"\W", "_", args.name)

    addons = [p for p in args.addons_path.split(",") if p] or [
        str(odoo_root / "addons"),
        *[str(p) for p in (odoo_root.parent.parent / r / odoo_root.name
                           for r in ("enterprise", "design-themes")) if p.is_dir()],
    ]
    names = [m for m in args.modules.split(",") if m] or sorted(
        p.parent.name for p in directory.glob("*/__manifest__.py")
    )
    order = topological(directory, names)

    with tempfile.TemporaryDirectory(prefix="odoo-bench-") as tmp:
        template = args.template
        if args.blank_template:
            template = args.blank_template
            if not template.startswith(PREFIX):
                raise SystemExit(f"--blank-template must start with {PREFIX}")
            ensure_blank_template(options, env, template, addons, odoo_root, args.odoo_python, tmp)
        isolate = {m for m in args.isolate.split(",") if m}
        depends = {
            n: ast.literal_eval(
                (directory / n / "__manifest__.py").read_text(encoding="utf-8").lstrip()
            ).get("depends", [])
            for n in order
        }
        groups = split_independent(order, depends, args.workers)
        results = []

        def work(index, group):
            # one database (and one Odoo process at a time) per worker
            worker_db = db if len(groups) == 1 else f"{db}_w{index}"
            conf = write_conf(options, [*addons, str(directory)], worker_db, tmp)
            installer = Installer(options, env, worker_db, conf, odoo_root, args.odoo_python, directory)
            installer.create_from(template)
            try:
                return installer.run(group, args.batch_size, isolate)
            finally:
                for name in (worker_db, installer.checkpoint):
                    if name != worker_db or not args.keep_db:
                        installer.drop(name)

        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=len(groups)) as pool:
            for group_results in pool.map(work, range(len(groups)), groups):
                results += group_results

    ok = sum(r["status"] == "OK" for r in results)
    blocked = sum(r["status"] == "BLOCKED" for r in results)
    print(f"\n{ok}/{len(results)} module(s) installed ({blocked} blocked by a failed dependency)")
    if args.output:
        pathlib.Path(args.output).write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
