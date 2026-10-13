# SPDX-License-Identifier: GPL-3.0-only
"""Run an adapter: python -m relaysms_adapter_sdk package.module:Class."""

import logging
import pkgutil
import sys

from relaysms_adapter_sdk import log
from relaysms_adapter_sdk.adapter import Adapter
from relaysms_adapter_sdk.runner import run

logger = logging.getLogger("relaysms_adapter_sdk")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(
            "usage: python -m relaysms_adapter_sdk package.module:Class",
            file=sys.stderr,
        )
        return 2

    log.configure()
    try:
        cls = pkgutil.resolve_name(argv[0])
        if not (isinstance(cls, type) and issubclass(cls, Adapter)):
            raise TypeError(f"{argv[0]} is not an Adapter subclass.")
        adapter = cls()
    except Exception:
        logger.exception("Could not start %s", argv[0])
        return 1

    run(adapter)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
