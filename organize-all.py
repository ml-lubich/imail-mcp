#!/usr/bin/env python3
"""Thin wrapper — prefer `imail organize`."""
from imail.organize import organize_inboxes

if __name__ == "__main__":
    import sys

    account = None
    limit = 200
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] in ("--account", "-a") and i + 1 < len(argv):
            account = argv[i + 1]
            i += 2
        elif argv[i] in ("--limit", "-n") and i + 1 < len(argv):
            limit = int(argv[i + 1])
            i += 2
        else:
            i += 1
    raise SystemExit(organize_inboxes(account=account, limit=limit))
