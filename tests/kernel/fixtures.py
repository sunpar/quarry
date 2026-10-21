"""Step code and SQL shared by the kernel tests, and by project tests that parse step code."""

import sys

import pytest

BUSY_LOOP = "import time\nwhile True:\n    time.sleep(0.01)\n"
# Code `ast.parse` gives up on with RecursionError and MemoryError, not SyntaxError.
UNPARSABLE = [
    pytest.param(
        "x = " + " + ".join(["1"] * 10_000),
        id="long-chain",
        marks=pytest.mark.skipif(sys.version_info >= (3, 14), reason="3.14 parses it"),
    ),
    pytest.param("x = " + "-" * 200_000 + "1", id="deep-unary"),
]
# Seconds of DuckDB work, which an interrupt ends at once. Each UNION ALL branch is one long
# task, which a worker thread runs whole: when an interrupt returns `.pl()` early, the next
# query waits for those tasks (over 4 s here) unless they stop.
HEAVY = "SELECT count(*) AS n FROM ({})".format(
    " UNION ALL ".join(["SELECT i FROM range(2000000000) t(i) WHERE hash(i) % 7 = 3"] * 4)
)
