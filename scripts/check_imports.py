"""Import every module under app/ to catch syntax and import errors early."""

import importlib
import pkgutil
import sys

import app


def main() -> int:
    failed = 0
    for module in pkgutil.walk_packages(app.__path__, prefix="app."):
        try:
            importlib.import_module(module.name)
        except Exception as exc:  # report every broken module, not only the first
            failed += 1
            sys.stderr.write(f"FAIL {module.name}: {type(exc).__name__}: {exc}\n")
    sys.stdout.write("IMPORT_OK\n" if not failed else f"IMPORT_FAILED {failed}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
