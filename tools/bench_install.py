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
        conf = write_conf(options, [*addons, str(directory)], db, tmp)

        subprocess.run([pg_tool(options, "dropdb"), *pg_args(options), "--if-exists", db],
                       env=env, check=True, capture_output=True)
        subprocess.run([pg_tool(options, "createdb"), *pg_args(options), "-T", template, db],
                       env=env, check=True, capture_output=True)
        results = []
        depends = {
            n: ast.literal_eval(
                (directory / n / "__manifest__.py").read_text(encoding="utf-8").lstrip()
            ).get("depends", [])
            for n in order
        }
        failed_modules = set()
        try:
            for name in order:
                blocking = [d for d in depends[name] if d in failed_modules]
                if blocking:
                    # not tried: a dependency of the set failed
                    failed_modules.add(name)
                    results.append({
                        "module": name, "status": "BLOCKED", "seconds": 0,
                        "error": "dependency failed: " + ", ".join(blocking), "tail": "",
                    })
                    print(f"{name:40} BLOCKED {results[-1]['error']}", flush=True)
                    continue
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
                if failed:
                    failed_modules.add(name)
                results.append({
                    "module": name,
                    "status": "FAILED" if failed else "OK",
                    "seconds": round(time.time() - start, 1),
                    "error": first_error(output) if failed else "",
                    "tail": "\n".join(output.splitlines()[-60:]) if failed else "",
                })
                print(f"{name:40} {results[-1]['status']:7} {results[-1]['error'][:160]}", flush=True)
        finally:
            if not args.keep_db:
                subprocess.run([pg_tool(options, "dropdb"), *pg_args(options), "--if-exists", db],
                               env=env, capture_output=True)

    ok = sum(r["status"] == "OK" for r in results)
    blocked = sum(r["status"] == "BLOCKED" for r in results)
    print(f"\n{ok}/{len(results)} module(s) installed ({blocked} blocked by a failed dependency)")
    if args.output:
        pathlib.Path(args.output).write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
