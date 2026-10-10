from __future__ import annotations

import re
import time

import pytest
from playwright.sync_api import Locator, Page, expect

from quarry.agent.types import AssistantTurn, ToolCall
from tests.e2e.test_ui import Serve, end, open_session, py, render, write

TRADES = (
    "df = pl.DataFrame({'ts': ['2024-01-02', '2024-01-03', '2024-01-04'], "
    "'sector': ['tech', 'tech', 'energy'], 'ret': [0.5, 1.0, -0.25]})"
)
POINTS = "df = pl.DataFrame({'x': [1.0, 2.0, 3.0], 'y': [0.5, 1.5, 1.0]})"
SERIES = (
    "from datetime import datetime\n"
    "df = pl.DataFrame({'ts': [datetime(2024, 1, d) for d in (2, 3, 4)], "
    "'px': [101.5, 102.25, 101.75]})"
)
CUSTOM = (
    'import { useQuery } from "@quarry/hooks";\n'
    "export default function V({ datasets }: { datasets: string[] }) {\n"
    '  const q = useQuery({ dataset: datasets[0] ?? "", limit: 2 });\n'
    "  return <p>{q.status}</p>;\n"
    "}\n"
)


def search(call_id: str) -> AssistantTurn:
    call = ToolCall(id=call_id, name="search_components", input={"dataset": "df", "tags": []})
    return AssistantTurn(text="", tool_calls=[call], stop="tool_use")


def code_for_view(page: Page) -> Locator:
    """Open the To code drawer once it renders the grouped query. A view reports its queries
    on a debounce, so its first snapshot can predate the query its schema leads to."""
    box = page.get_by_role("textbox", name="Python")
    deadline = time.monotonic() + 30
    while True:
        page.get_by_role("button", name="To code").click()
        expect(box).to_have_value(re.compile(r"\S"), timeout=30_000)
        if "group_by" in box.input_value() or time.monotonic() > deadline:
            return box
        page.wait_for_timeout(500)


def test_bar_line_to_code_runs_as_a_step(serve: Serve, page: Page) -> None:
    server = serve([py("c1", TRADES), render("c2", "bar-line"), end("bars")])
    open_session(page, server, "bar chart")
    expect(page.get_by_text("bars", exact=True)).to_be_visible(timeout=30_000)
    frame = page.frame_locator("iframe[title='View for step 1']")
    expect(frame.get_by_label("Aggregate")).to_be_visible(timeout=30_000)
    box = code_for_view(page)
    expect(box).to_have_value(re.compile("group_by"))
    # Only the grouped query: the view's `{dataset, limit: 1}` placeholder is not recorded.
    expect(box).not_to_have_value(re.compile(r"slice\(0, 1\)"))
    page.get_by_role("button", name="Run as step").click()
    step = page.get_by_label("Step 2")
    expect(step.get_by_text("Done")).to_be_visible(timeout=30_000)
    expect(step.get_by_text("df_1", exact=True)).to_be_visible()
    # The grouped frame has the category and the aggregate; a placeholder slice has three.
    expect(step.get_by_title("2 columns")).to_be_visible()
    expect(step.get_by_text("df_2", exact=True)).to_have_count(0)


def test_save_custom_view_to_library(serve: Serve, page: Page) -> None:
    turns = [py("c1", TRADES), write("c2", CUSTOM), end("custom")]
    server = serve([*turns, search("c3"), render("c4", "my-status"), end("reused")])
    open_session(page, server, "custom view")
    expect(page.get_by_text("custom", exact=True)).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Save to library").click()
    page.get_by_label("Id", exact=True).fill("my-status")
    page.get_by_label("Name", exact=True).fill("My status")
    page.get_by_role("button", name="Save to library", exact=True).last.click()
    expect(page.get_by_text("Saved my-status to your library")).to_be_visible(timeout=30_000)

    # A later step finds the saved component by search and mounts it from the library.
    box = page.get_by_role("textbox")
    expect(box).to_be_enabled()
    box.fill("use my status view")
    box.press("Enter")
    expect(page.get_by_text("reused", exact=True)).to_be_visible(timeout=30_000)
    frame = page.frame_locator("iframe[title='View for step 2']")
    expect(frame.get_by_text("success", exact=True)).to_be_visible(timeout=30_000)
    found = [
        r.content
        for _, messages, _ in server.provider.calls
        for m in messages
        for r in m.tool_results
        if r.call_id == "c3"
    ]
    assert found and '"my-status"' in found[0], found


@pytest.mark.parametrize(
    ("code", "component", "chart"),
    [
        # Plotly draws its axes in SVG; a 2.5 tick means the x range came from the data.
        (POINTS, "scatter", ".js-plotly-plot .xtick:has-text('2.5')"),
        (SERIES, "large-series", "div[_echarts_instance_] canvas"),
    ],
)
def test_bundled_chart_mounts_under_the_csp(
    serve: Serve, page: Page, code: str, component: str, chart: str
) -> None:
    server = serve([py("c1", code), render("c2", component), end("charted")])
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"uncaught: {e}"))
    open_session(page, server, component)
    expect(page.get_by_text("charted", exact=True)).to_be_visible(timeout=30_000)
    frame = page.frame_locator("iframe[title='View for step 1']")
    expect(frame.locator(chart).first).to_be_visible(timeout=60_000)
    # A query error renders as a <pre> in the frame, a mount error as the host's overlay.
    expect(frame.locator("pre")).to_have_count(0)
    expect(page.get_by_text("The view did not mount.")).to_have_count(0)
    failures = [
        e
        for e in errors
        if e.startswith("uncaught: ") or "Content Security Policy" in e or "CORS" in e
    ]
    assert not failures, errors
