# SPDX-License-Identifier: GPL-3.0-only

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from db import get_session
from models.token import Token, update_token_data


def apply_migrated_sessions(sessions_file: str, platform: str) -> None:
    sessions = json.loads(Path(sessions_file).read_text(encoding="utf-8"))

    with get_session() as db:
        tokens = db.scalars(select(Token).where(Token.platform == platform)).all()
        by_account_id = {t.token_data.get("account_id"): t for t in tokens}

        updated = 0
        missing = []
        for account_id, session in sessions.items():
            token = by_account_id.get(account_id)
            if not token:
                missing.append(account_id)
                continue
            update_token_data(token, {**token.token_data, "token": session}, db)
            updated += 1

    print(f"Updated {updated} token(s).")
    if missing:
        print(f"No token found for: {', '.join(missing)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sessions_file", help="Path to migrated_sessions.json")
    parser.add_argument(
        "--platform", default="telegram", help="Platform name (default: %(default)s)"
    )
    args = parser.parse_args()
    apply_migrated_sessions(args.sessions_file, args.platform)


if __name__ == "__main__":
    main()
