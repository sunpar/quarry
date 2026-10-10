from __future__ import annotations

from collections.abc import Callable

from playwright.sync_api import Page, expect

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
