"""Allow ``python -m notsucky``."""

import sys

from notsucky.main import main

if __name__ == "__main__":
    sys.exit(main())
