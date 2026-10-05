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


def topological(directory, names):
    manifests = {
        n: ast.literal_eval((directory / n / "__manifest__.py").read_text(encoding="utf-8"))
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
    lines = [m.group(0) for m in ERROR_RE.finditer(output)]
    # the last "XxxError: message" line of the traceback is the most useful
    for line in reversed(lines):
        if re.match(r"^\s*[\w.]+(?:Error|Exception)\b", line):
            return line.strip()[:500]
    return lines[0].strip()[:500] if lines else output.strip().splitlines()[-1][:500]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory")
    parser.add_argument("--config", required=True, help="Odoo config of the target (db access)")
    parser.add_argument("--template", required=True, help="blank database to copy")
    parser.add_argument("--odoo-root", required=True)
    parser.add_argument("--odoo-python", required=True)
    parser.add_argument("--addons-path", default="", help="reference addons (default: from --odoo-root)")
    parser.add_argument("--modules", default="", help="comma separated (default: all)")
    parser.add_argument("--name", default="run")
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
        conf = pathlib.Path(tmp) / "bench.conf"
        bench = configparser.ConfigParser(interpolation=None)
        bench["options"] = {
            k: v for k, v in options.items()
            if k.startswith("db_") and k != "db_name" or k == "pg_path"
        }
        bench["options"].update({
            "addons_path": ",".join([*addons, str(directory)]),
            "data_dir": str(pathlib.Path(tmp) / "data"),
            "db_name": db,
            "dbfilter": f"^{db}$",
            "list_db": "False",
            "max_cron_threads": "0",
        })
        with conf.open("w", encoding="utf-8") as f:
            bench.write(f)

        subprocess.run([pg_tool(options, "dropdb"), *pg_args(options), "--if-exists", db],
                       env=env, check=True, capture_output=True)
        subprocess.run([pg_tool(options, "createdb"), *pg_args(options), "-T", args.template, db],
                       env=env, check=True, capture_output=True)
        results = []
        try:
            for name in order:
                start = time.time()
                proc = subprocess.run(
                    [args.odoo_python, str(odoo_root / "odoo-bin"), "-c", str(conf),
                     "-d", db, "-i", name, "--stop-after-init", "--no-http",
                     "--log-level=warn"],
                    capture_output=True, env=dict(env, PYTHONUTF8="1"),
                )
                output = (proc.stdout + proc.stderr).decode("utf-8", "replace")
                failed = proc.returncode != 0 or re.search(
                    r" (ERROR|CRITICAL) .*(Failed to load|Failed to initialize|"
                    r"Some modules have inconsistent states|Traceback)|^Traceback",
                    output, re.M,
                )
                results.append({
                    "module": name,
                    "status": "FAILED" if failed else "OK",
                    "seconds": round(time.time() - start, 1),
                    "error": first_error(output) if failed else "",
                })
                print(f"{name:40} {results[-1]['status']:7} {results[-1]['error'][:160]}", flush=True)
        finally:
            if not args.keep_db:
                subprocess.run([pg_tool(options, "dropdb"), *pg_args(options), "--if-exists", db],
                               env=env, capture_output=True)

    ok = sum(r["status"] == "OK" for r in results)
    print(f"\n{ok}/{len(results)} module(s) installed")
    if args.output:
        pathlib.Path(args.output).write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
