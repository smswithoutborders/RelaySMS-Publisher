# SPDX-License-Identifier: GPL-3.0-only

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from db import get_session
from models.token import Token


def list_phone_numbers(platform: str) -> None:
    with get_session() as db:
        tokens = db.scalars(select(Token).where(Token.platform == platform)).all()
        for token in tokens:
            account_id = token.token_data.get("account_id")
            if account_id:
                print(account_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--platform", default="telegram", help="Platform name (default: %(default)s)"
    )
    args = parser.parse_args()
    list_phone_numbers(args.platform)


if __name__ == "__main__":
    main()
