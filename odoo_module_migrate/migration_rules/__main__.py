# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
"""Validate the migration rules.

    python -m odoo_module_migrate.migration_rules [--step migrate_190_200]
        [--odoo-source D:/Odoo/odoo/20.0/addons ...] [--audit] [--details] [--strict]

Exit code 1 on an error (2 with --strict on a warning).
"""

from __future__ import annotations

import argparse
import sys

from .validation import summary, validate


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m odoo_module_migrate.migration_rules", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--step", help="only summarise this step folder (migrate_XXX_YYY)")
    parser.add_argument("--odoo-source", action="append", default=[],
                        help="addons path of the target Odoo: checks that the rule targets exist")
    parser.add_argument("--audit", action="store_true", help="list rules that could become more semantic")
    parser.add_argument("--details", action="store_true", help="print every finding")
    parser.add_argument("--strict", action="store_true", help="warnings fail too")
    args = parser.parse_args(argv)

    report = validate(odoo_sources=args.odoo_source)
    print(summary(report, args.step))
    shown = report.findings if args.details else report.errors
    for finding in shown:
        if args.step and args.step not in finding.where:
            continue
        print(finding)
    if args.audit:
        for name, items in sorted(report.audit.items()):
            items = [i for i in items if not args.step or args.step in i]
            print(f"\n{name}: {len(items)}")
            for item in items[:50]:
                print(f"  {item}")
            if len(items) > 50:
                print(f"  ... {len(items) - 50} more")
    if report.errors:
        return 1
    return 2 if args.strict and report.findings else 0


if __name__ == "__main__":
    sys.exit(main())
