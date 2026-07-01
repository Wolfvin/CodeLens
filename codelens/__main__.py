"""Allow ``python -m codelens`` to run the CLI."""

import sys

from . import main


if __name__ == "__main__":
    sys.exit(main())
