"""Entry point for both `python -m cwtrack` and the `cwtrack` console script.

This wrapper exists so a CwError becomes a readable message and an exit code.
Without it, `cwtrack gaps` with no store prints a Python traceback ending in
CwError - which is a correct error for the developer and a poor first impression
for a student who just installed the tool and does not yet have data.

Two entry paths must behave identically, and both land here: pip's console-script
shim calls `main()` directly rather than going through `__main__.py`, so the
console script needs `main` itself to do the conversion.
"""

from __future__ import annotations

import sys

from .cli import main as _main
from .client import CwError

#: Exit code for "your data is not where I looked", distinct from a crash. A shell
#: can tell this apart from 1, and so can a student who reads the last line.
EXIT_NO_DATA = 2


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    try:
        return _main(argv)
    except CwError as exc:
        # No traceback. The message is the whole point of CwError, and a traceback
        # buries it under stack frames that mean nothing to the reader.
        print("\nخطا: {}".format(exc), file=sys.stderr)
        print("", file=sys.stderr)
        return EXIT_NO_DATA
    except KeyboardInterrupt:
        print("\nلغو شد", file=sys.stderr)
        return 130


def _force_utf8_streams() -> None:
    """Persian errors are Persian too, so the guard runs before anything prints.

    cli.main() also does this, but the error path is reached precisely when cli
    main raised - and the message written here would then hit a cp1252 console.
    """
    import contextlib

    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    sys.exit(main())
