from __future__ import annotations

from playwright.sync_api import Page, expect

from tests.e2e.test_ui import Serve, end, open_session, pl_df, py, render

TIDY = "import polars as pl\n" + pl_df + "\n"


def test_save_recall_and_canvas(serve: Serve, page: Page) -> None:
    server = serve([py("c1", pl_df), render("c2", "data-table"), end("Here is df"), end(TIDY)])
    open_session(page, server, "show df")
    expect(page.get_by_text("Here is df")).to_be_visible(timeout=30_000)

    page.on("dialog", lambda d: d.accept("Momentum") if d.type == "prompt" else d.accept())
    page.get_by_role("button", name="New project").click()
    expect(page.get_by_role("button", name="Momentum", exact=True)).to_be_visible()

    page.get_by_role("button", name="Pin to canvas").click()
    page.get_by_label("Name").fill("closes")
    page.get_by_role("dialog").get_by_role("button", name="Save view").click()
    expect(page.get_by_text("Saved view closes")).to_be_visible(timeout=60_000)

    page.get_by_role("button", name="New session").click()
    page.get_by_role("button", name="Momentum", exact=True).click()
    page.get_by_role("button", name="Recall df", exact=True).click()
    expect(page.get_by_text("Recall df from Momentum")).to_be_visible(timeout=30_000)
    expect(page.get_by_text("Done", exact=True)).to_be_visible(timeout=30_000)

    page.get_by_role("button", name="Open Momentum").click()
    page.get_by_role("tab", name="Canvas").click()
    frame = page.frame_locator("iframe[title='Canvas card closes']")
    expect(frame.get_by_text("102.25")).to_be_visible(timeout=30_000)
