import sys

from spectra_scanner.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["watch", *sys.argv[1:]]))
