"""Read-only S2.2a analysis entry point; no scanner access."""

from spectra_centering.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
