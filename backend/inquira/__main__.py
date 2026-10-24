"""Operator commands:  python -m inquira <command>

  migrate          apply database migrations (also runs automatically at startup)
  rotate-secrets   re-encrypt stored credentials with the current INQUIRA_SECRET_KEY
"""

from __future__ import annotations

import sys


def main(argv: list[str]) -> int:
    command = argv[0] if argv else ""
    if command == "migrate":
        from inquira.db import migrate

        migrate()
        print("Database is up to date.")
        return 0
    if command == "rotate-secrets":
        from inquira.db import SessionLocal
        from inquira.services.settings_store import rotate_secrets

        with SessionLocal() as db:
            print(f"Re-encrypted {rotate_secrets(db)} stored secret(s) with the current key.")
        print("You can now remove the old key from INQUIRA_PREVIOUS_SECRET_KEYS.")
        return 0
    print(__doc__)
    return 0 if command in ("", "-h", "--help") else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
