"""Step code and SQL shared by the kernel tests."""

BUSY_LOOP = "import time\nwhile True:\n    time.sleep(0.01)\n"
# Seconds of DuckDB work, which an interrupt ends at once. Each UNION ALL branch is one long
# task, which a worker thread runs whole: when an interrupt returns `.pl()` early, the next
# query waits for those tasks (over 4 s here) unless they stop.
HEAVY = "SELECT count(*) AS n FROM ({})".format(
    " UNION ALL ".join(["SELECT i FROM range(2000000000) t(i) WHERE hash(i) % 7 = 3"] * 4)
)
