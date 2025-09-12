# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import argparse
import argcomplete
import sys

from . import tools
from .log import setup_logger
from .migration import Migration


def get_parser():
    main_parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)

    main_parser.add_argument(
        "-d", "--directory", default="./", type=str,
        help="Target modules directory containing Odoo modules to migrate."
    )

    main_parser.add_argument(
        "-m", "--modules", type=str,
        help="Target modules to migrate (comma-separated). If not set, all modules will be migrated."
    )

    main_parser.add_argument(
        "-i", "--init-version-name", required=True, type=str,
        choices=tools._get_available_init_version_names()
    )

    main_parser.add_argument(
        "-t", "--target-version-name", type=str,
        choices=tools._get_available_target_version_names(),
        default=tools._get_latest_version_name(),
        help="Target Odoo version (default: latest)."
    )

    main_parser.add_argument(
        "-fp", "--format-patch", action="store_true",
        help="Get code from previous branch."
    )

    main_parser.add_argument(
        "-rn", "--remote-name", default="origin", type=str
    )

    main_parser.add_argument(
        "-ll", "--log-level", default="INFO", type=str,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    )

    main_parser.add_argument(
        "-lp", "--log-path", default=False, type=str
    )

    main_parser.add_argument(
        "-lpwo", "--log-path-warninglevelonly", default=False, type=str
    )

    main_parser.add_argument(
        "-nc", "--no-commit", action="store_true",
        help="Skip git commit of changes."
    )

    main_parser.add_argument(
        "-npc", "--no-pre-commit", dest="pre_commit", action="store_false",
        help="Skip pre-commit execution."
    )

    main_parser.add_argument(
        "-nrmf", "--no-remove-migration-folder", dest="remove_migration_folder", action="store_false",
        help="Skip removing migration folder."
    )

    main_parser.add_argument(
        "--no-oca-modules", action="store_true",
        help="Skip migration of OCA modules."
    )

    main_parser.add_argument(
        "--oca-file-list",
        action="store_true",
        default=False,
        help="Generate OCA_MODULES.md file listing all OCA modules found in the project.",
    )

    return main_parser


def main(args=None):
    parser = get_parser()
    argcomplete.autocomplete(parser, always_complete_options=False)
    args = parser.parse_args(args)
    
    setup_logger(args.log_level, args.log_path, args.log_path_warninglevelonly)
    
    if args.oca_file_list:
        from .oca_generator import generate_oca_file_list
        generate_oca_file_list(args.directory)
        return

    try:
        module_names = [x.strip() for x in (args.modules or "").split(",") if x.strip()]

        migration = Migration(
            args.directory,
            args.init_version_name,
            args.target_version_name,
            module_names,
            args.format_patch,
            args.remote_name,
            not args.no_commit,
            args.pre_commit,
            args.remove_migration_folder,
            args.no_oca_modules,
        )

        # run Migration
        migration.run()

    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
