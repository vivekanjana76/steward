"""``python -m steward.evals`` → run the eval suite and gate against baseline."""

from __future__ import annotations

import sys

from steward.evals.run import main

if __name__ == "__main__":
    sys.exit(main())
