"""Ponto de entrada do ANM2000 Backup Manager."""

import sys

from anmbackup.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
