from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Page, Route, expect

from quarry.agent.types import AssistantTurn, ToolCall
from tests.e2e.conftest import RunningServer

Serve = Callable[[list[AssistantTurn]], RunningServer]

pl_df = "df = pl.DataFrame({'ts': ['2024-01-02', '2024-01-03'], 'px': [101.5, 102.25]})"


def py(call_id: str, code: str) -> AssistantTurn:
    return AssistantTurn(
        text="",
        tool_calls=[ToolCall(id=call_id, name="run_python", input={"code": code})],
        stop="tool_use",
    )


def render(call_id: str, component_id: str) -> AssistantTurn:
    call = ToolCall(
        id=call_id,
        name="render_view",
        input={"component_id": component_id, "datasets": ["df"], "initial_state": "{}"},
    )
    return AssistantTurn(text="", tool_calls=[call], stop="tool_use")


def write(call_id: str, source: str) -> AssistantTurn:
    call = ToolCall(
        id=call_id,
        name="write_view",
        input={"source": source, "datasets": ["df"], "initial_state": "{}"},
    )
    return AssistantTurn(text="", tool_calls=[call], stop="tool_use")


def end(text: str = "done") -> AssistantTurn:
    return AssistantTurn(text=text, tool_calls=[], stop="end")


def open_session(page: Page, server: RunningServer, prompt: str) -> None:
    page.goto(f"{server.base_url}/#token={server.token}")
    page.get_by_role("button", name="New session").click()
    box = page.get_by_role("textbox")
    expect(box).to_be_enabled()
    box.fill(prompt)
    box.press("Enter")


def test_table_view_round_trip(serve: Serve, page: Page) -> None:
    server = serve([py("c1", pl_df), render("c2", "data-table"), end("Here is df")])
    open_session(page, server, "show df")
    expect(page.get_by_text("Here is df")).to_be_visible(timeout=30_000)
    frame = page.frame_locator("iframe[title='View for step 1']")
    expect(frame.get_by_text("102.25")).to_be_visible(timeout=30_000)
    expect(page.get_by_role("textbox")).to_be_enabled()


@pytest.mark.parametrize("component", ["data-table", "data-table-tanstack"])
def test_table_filters_sort_history_and_executed_to_code(
    serve: Serve, page: Page, component: str
) -> None:
    code = (
        "from datetime import date\n"
        "df = pl.DataFrame({'symbol': ['[A', 'B', '[C', 'D', '[E'], "
        "'price': [1.5, 3.0, 2.5, None, 4.0], "
        "'day': [date(2026, 10, d) for d in (12, 13, 14, 14, 14)]})"
    )
    server = serve([py("c1", code), render("c2", component), end("filtered table")])
    open_session(page, server, component)
    frame = page.frame_locator("iframe[title='View for step 1']")
    expect(frame.get_by_text("1.5", exact=True)).to_be_visible(timeout=30_000)
    # A changed sort keeps the current rows on screen until its query answers.
    held: list[Route] = []

    def hold(route: Route) -> None:
        held.append(route)

    page.route("**/query", hold)
    with page.expect_response(
        lambda r: r.url.endswith("/snapshots") and r.request.method == "POST"
    ):
        frame.get_by_role("columnheader", name=re.compile(r"^symbol")).click()
    expect(frame.get_by_text("Loading", exact=True)).to_be_visible()
    expect(frame.get_by_text("1.5", exact=True)).to_be_visible()
    assert held
    for route in held:
        route.continue_()
    page.unroute("**/query")
    expect(frame.get_by_text("Loading", exact=True)).to_have_count(0)
    # First save a numeric predicate, then a second snapshot with server-side sort.
    frame.get_by_label("Filter column").select_option("price")
    frame.get_by_label("Filter operator").select_option("ge")
    frame.get_by_label("Filter value").fill("2")
    with page.expect_response(
        lambda r: r.url.endswith("/snapshots") and r.request.method == "POST"
    ) as response:
        frame.get_by_role("button", name="Apply filter").click()
    assert response.value.ok
    expect(frame.get_by_text("1.5", exact=True)).to_have_count(0)
    header = frame.get_by_role("columnheader", name=re.compile(r"^price"))
    with page.expect_response(
        lambda r: r.url.endswith("/snapshots") and r.request.method == "POST"
    ):
        header.click()
        header.click()
    session_id = parse_qs(urlsplit(page.url).fragment)["session"][0]
    session_url = f"{server.base_url}/sessions/{session_id}"
    headers = {"Authorization": f"Bearer {server.token}"}
    session = page.request.get(session_url, headers=headers).json()
    snapshots = session["steps"][0]["view"]["snapshots"]
    sorted_index = len(snapshots) - 1
    query = snapshots[-1]["queries"][0]
    assert query["filters"] == [{"col": "price", "op": "ge", "value": 2}]
    assert query["sort"] == [{"col": "price", "desc": True}]

    # Literal text and Date filters compose with the numeric predicate.
    for column, operator, value in (("symbol", "contains", "["), ("day", "eq", "2026-10-14")):
        frame.get_by_label("Filter column").select_option(column)
        frame.get_by_label("Filter operator").select_option(operator)
        frame.get_by_label("Filter value").fill(value)
        with page.expect_response(
            lambda r: r.url.endswith("/snapshots") and r.request.method == "POST"
        ):
            frame.get_by_role("button", name="Apply filter").click()
    expect(frame.get_by_text("[C", exact=True)).to_be_visible()
    expect(frame.get_by_text("B", exact=True)).to_have_count(0)

    # Restore an actual earlier snapshot, including its filter and descending sort.
    slider = page.get_by_role("slider")
    slider.fill(str(sorted_index))
    expect(frame.get_by_text("B", exact=True)).to_be_visible()
    expect(frame.get_by_role("button", name="Remove symbol filter 2")).to_have_count(0)
    slider.fill(slider.get_attribute("max") or "0")
    expect(frame.get_by_text("B", exact=True)).to_have_count(0)
    page.get_by_role("button", name="To code").click()
    python = page.get_by_role("textbox", name="Python")
    expect(python).to_have_value(re.compile(r"str\.contains.*literal=True"))
    assert ".sort(" in python.input_value()
    # The drawer opens below the History slider and stays inside the step's column.
    drawer = page.get_by_role("region", name="To code").bounding_box()
    card = page.get_by_role("article", name="Step 1").bounding_box()
    assert drawer is not None and card is not None
    assert drawer["x"] + drawer["width"] <= card["x"] + card["width"]
    page.get_by_role("button", name="Run as step").click()
    expect(page.get_by_label("Step 2").get_by_text("Done")).to_be_visible(timeout=30_000)
    result = page.request.post(
        f"{session_url}/query", headers=headers, data={"dataset": "df_1"}
    ).json()
    assert result["rows"] == [
        {"symbol": "[E", "price": 4.0, "day": "2026-10-14"},
        {"symbol": "[C", "price": 2.5, "day": "2026-10-14"},
    ]


def test_refused_import_offers_fix(serve: Serve, page: Page) -> None:
    bad = 'import _ from "lodash";\nexport default function V() { return <div>{typeof _}</div>; }'
    server = serve([py("c1", pl_df), write("c2", bad), end("drew it"), end("fixed")])
    open_session(page, server, "custom view")
    expect(page.get_by_text('"lodash" is not available in views', exact=False)).to_be_visible(
        timeout=30_000
    )
    page.get_by_role("button", name="Fix this view").click()
    expect(page.get_by_text("fixed", exact=True)).to_be_visible(timeout=30_000)
    expect(page.get_by_text("Fix the view so it mounts.")).to_be_visible()


# The host is served from 127.0.0.1, so localhost is another origin.
LEAVE = """\
import { useEffect } from "react";
export default function V() {
  useEffect(() => {
    location.assign(location.href.replace("//127.0.0.1", "//localhost") + "?rows=1");
  }, []);
  return <p>leaving</p>;
}
"""


def test_a_view_cannot_navigate_its_frame_to_another_origin(serve: Serve, page: Page) -> None:
    server = serve([py("c1", pl_df), write("c2", LEAVE), end("drew it")])
    refused: list[str] = []
    off_site: list[str] = []
    page.on("console", lambda m: refused.append(m.text) if "frame-src" in m.text else None)
    page.on("request", lambda r: off_site.append(r.url) if "//localhost" in r.url else None)
    open_session(page, server, "leave")
    for _ in range(300):  # until the frame tries to leave, for up to 30 s
        if refused or off_site:
            break
        page.wait_for_timeout(100)
    assert not off_site, off_site
    assert refused
