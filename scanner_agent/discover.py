"""Run with the scanner-agent virtual environment, independent of FastAPI."""

import sys

from spectra_scanner.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["discover", *sys.argv[1:]]))
