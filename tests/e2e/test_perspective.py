from __future__ import annotations

from collections.abc import Callable

from playwright.sync_api import Page, expect

from quarry.agent.types import AssistantTurn
from tests.e2e.conftest import RunningServer
from tests.e2e.test_ui import end, open_session, py, write

MIXED = (
    "from datetime import date, datetime\nfrom decimal import Decimal\n"
    "df = pl.DataFrame({'d': [date(2024, 1, 2), date(2024, 1, 3)], "
    "'ts': [datetime(2024, 1, 2, 9), datetime(2024, 1, 3, 9)], "
    "'px': pl.Series([Decimal('1.50'), Decimal('2.25')], dtype=pl.Decimal(38, 2)), "
    "'sym': pl.Series(['A', 'B'], dtype=pl.Categorical), 's': ['x', 'y']})\n"
)
VIEW = """\
import { useQuery } from "@quarry/hooks";
import { PerspectiveViewer } from "@quarry/perspective";
export default function V({ datasets }: { datasets: string[] }) {
  const q = useQuery({ dataset: datasets[0] ?? "", format: "arrow" });
  if (q.status !== "success" || q.arrow === null) return <p>{q.status}</p>;
  return (
    <div style={{ height: 380 }}>
      <p data-testid="rows">{q.rowCount}</p>
      <PerspectiveViewer arrow={q.arrow} />
    </div>
  );
}
"""


def test_perspective_mounts_in_the_sandbox(
    serve: Callable[[list[AssistantTurn]], RunningServer], page: Page
) -> None:
    server = serve([py("c1", MIXED), write("c2", VIEW), end("pivot it")])
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    open_session(page, server, "pivot df")
    frame = page.frame_locator("iframe[title='View for step 1']")
    expect(frame.get_by_test_id("rows")).to_have_text("2", timeout=60_000)
    expect(frame.locator("perspective-viewer")).to_be_visible(timeout=60_000)
    # The datagrid plugin renders one header cell per column once the table is loaded.
    header = frame.locator("perspective-viewer regular-table th", has_text="px")
    expect(header).to_be_visible(timeout=60_000)
    blocked = [e for e in errors if "Content Security Policy" in e or "CORS" in e]
    assert not blocked, blocked


SWITCH = """\
import { useQuery, useViewState } from "@quarry/hooks";
import { PerspectiveViewer } from "@quarry/perspective";
export default function V({ datasets }: { datasets: string[] }) {
  const [limit, setLimit] = useViewState("limit", 2);
  const q = useQuery({ dataset: datasets[0] ?? "", format: "arrow", limit });
  if (q.status !== "success" || q.arrow === null) return <p>{q.status}</p>;
  return (
    <div style={{ height: 380 }}>
      <button onClick={() => setLimit(3 - limit)}>switch</button>
      <p data-testid="rows">{q.rowCount}</p>
      <PerspectiveViewer arrow={q.arrow} />
    </div>
  );
}
"""


def test_perspective_takes_new_query_results(
    serve: Callable[[list[AssistantTurn]], RunningServer], page: Page
) -> None:
    server = serve([py("c1", MIXED), write("c2", SWITCH), end("pivot it")])
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    open_session(page, server, "pivot df")
    frame = page.frame_locator("iframe[title='View for step 1']")
    header = frame.locator("perspective-viewer regular-table th", has_text="px")
    expect(header).to_be_visible(timeout=60_000)
    # Limit 1 is a new query, so the viewer unmounts while it loads; limit 2 is then
    # answered from the cache, so the same viewer swaps tables. Neither may raise.
    for rows in ("1", "2"):
        frame.get_by_role("button", name="switch").click()
        expect(frame.get_by_test_id("rows")).to_have_text(rows, timeout=60_000)
        expect(header).to_be_visible(timeout=60_000)
    assert not errors, errors
