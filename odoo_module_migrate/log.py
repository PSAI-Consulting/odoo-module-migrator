# Copyright (C) 2015 ACSONE SA/NV
# Part of this file come from the Acsone git-aggregator project
# https://github.com/acsone/git-aggregator
# Copyright (C) 2019 - Today: GRAP (http://www.grap.coop)
# @author: Sylvain LE GAL (https://twitter.com/legalsylvain)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).


from colorama import Fore, Style
import time

import logging

logger = logging.getLogger(__name__)

LEVEL_COLORS = {
    "DEBUG": Fore.BLUE,
    "INFO": Fore.GREEN,
    "WARNING": Fore.YELLOW,
    "ERROR": Fore.RED,
    "CRITICAL": Fore.RED,
}


def setup_logger(level, file_path=False, warning_level_only_file_path=False):
    if not file_path:
        handler = logging.StreamHandler()
        handler.setFormatter(OdooMigrateFormatter())
        if warning_level_only_file_path:
            warning_handler = logging.FileHandler(warning_level_only_file_path)
            warning_handler.setLevel(logging.WARNING)
            warning_handler.setFormatter(MarkdownLogFormatter())
            warning_handler.stream.reconfigure(encoding="utf-8")
            logger.addHandler(warning_handler)
    else:
        handler = logging.FileHandler(file_path)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s"
            )
        )
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, str(level)))

class MarkdownLogFormatter(logging.Formatter):
    COLOR_MAP = {
        "DEBUG": "",
        "INFO": "",
        "WARNING": "⚠️ ",
        "ERROR": "❌ ",
        "CRITICAL": "🔥 ",
    }

    def format(self, record):
        prefix = self.COLOR_MAP.get(record.levelname, "")
        if record.levelname in ["ERROR", "CRITICAL"]:
            level = f"<span style='color:red;'>**{record.levelname}**</span>"
        elif record.levelname == "WARNING":
            level = f"<span style='color:orange;'>*{record.levelname}*</span>"
        else:
            level = f"*{record.levelname}*"
        asctime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created))
        return f"- [ ] {asctime},{int(record.msecs)} {prefix}{level} {record.getMessage()}"

class OdooMigrateFormatter(logging.Formatter):
    def format(self, record):
        """Overwrite format() function to use custom formatter"""
        record.message = record.getMessage()
        record.asctime = time.strftime("%H:%M:%S", self.converter(record.created))

        prefix = self.default_prefix_template(record) % record.__dict__
        return (prefix + " " + record.message).replace("\n", "\n" + "".ljust(23, " "))

    def default_prefix_template(self, record):
        """Return the prefix for the log message. Template for Formatter.

        :param: record: :py:class:`logging.LogRecord` object. this is passed in
        from inside the :py:meth:`logging.Formatter.format` record.

        """
        reset = [Style.RESET_ALL]
        levelname = [
            LEVEL_COLORS.get(record.levelname),
            Style.BRIGHT,
            "%(levelname)-10s",
            Style.RESET_ALL,
            " ",
        ]
        asctime = [
            "",
            Fore.BLACK,
            Style.DIM,
            Style.BRIGHT,
            "%(asctime)-10s",
            Fore.RESET,
            Style.RESET_ALL,
            " ",
        ]

        return "".join(reset + asctime + levelname + reset)
