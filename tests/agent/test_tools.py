import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from quarry.agent.tools import TOOL_DEFS, ToolExecutor
from quarry.agent.transpile import CommandTranspiler, NoopTranspiler, Transpiler
from quarry.agent.types import ToolCall
from quarry.components.library import ComponentLibrary
from quarry.kernel.client import KernelClient
from quarry.query import Json
from tests.components.test_library import write_broken_components, write_component

MAKE_DF: dict[str, Json] = {"code": "df = pl.DataFrame({'a': [1]})"}


@pytest.fixture
def kernel(tmp_path: Path) -> Iterator[KernelClient]:
    client = KernelClient.spawn(tmp_path)
    yield client
    client.close()


def executor(
    kernel: KernelClient, tmp_path: Path, transpiler: Transpiler | None = None
) -> ToolExecutor:
    write_component(tmp_path / "lib", "table", ["table"], [])
    return ToolExecutor(
        kernel=kernel,
        library=ComponentLibrary([tmp_path / "lib"]),
        transpiler=transpiler or NoopTranspiler(),
    )


def test_tool_defs_names() -> None:
    assert [t.name for t in TOOL_DEFS] == [
        "run_python",
        "describe_dataset",
        "search_components",
        "render_view",
        "write_view",
    ]


def test_run_python_success_and_failure(kernel: KernelClient, tmp_path: Path) -> None:
    ex = executor(kernel, tmp_path)
    ok = ex.run(
        ToolCall(id="1", name="run_python", input={"code": "df = pl.DataFrame({'a': [1]})"})
    )
    assert ok.is_error is False
    body = json.loads(ok.content)
    assert body["writes"] == ["df"]
    bad = ex.run(ToolCall(id="2", name="run_python", input={"code": "1/0"}))
    assert bad.is_error is True
    assert "ZeroDivisionError" in bad.content
    assert [(code, r.status) for code, r in ex.runs] == [
        ("df = pl.DataFrame({'a': [1]})", "ok"),
        ("1/0", "error"),
    ]


def test_describe_dataset(kernel: KernelClient, tmp_path: Path) -> None:
    ex = executor(kernel, tmp_path)
    ex.run(ToolCall(id="1", name="run_python", input={"code": "df = pl.DataFrame({'a': [1, 2]})"}))
    out = ex.run(ToolCall(id="2", name="describe_dataset", input={"name": "df"}))
    assert json.loads(out.content)["rows"] == 2
    missing = ex.run(ToolCall(id="3", name="describe_dataset", input={"name": "zz"}))
    assert missing.is_error is True


def test_search_and_render_view(kernel: KernelClient, tmp_path: Path) -> None:
    ex = executor(kernel, tmp_path)
    ex.run(ToolCall(id="1", name="run_python", input=MAKE_DF))
    found = ex.run(
        ToolCall(id="2", name="search_components", input={"dataset": "df", "tags": ["table"]})
    )
    assert json.loads(found.content)[0]["id"] == "table"
    rendered = ex.run(
        ToolCall(
            id="3",
            name="render_view",
            input={"component_id": "table", "datasets": ["df"], "initial_state": "{}"},
        )
    )
    assert rendered.is_error is False
    assert ex.view is not None and ex.view.component_id == "table"
    assert ex.view.source.startswith("export default")
    unknown = ex.run(
        ToolCall(
            id="4",
            name="render_view",
            input={"component_id": "nope", "datasets": ["df"], "initial_state": "{}"},
        )
    )
    assert unknown.is_error is True
    missing_ds = ex.run(
        ToolCall(
            id="5",
            name="render_view",
            input={"component_id": "table", "datasets": ["zz"], "initial_state": "{}"},
        )
    )
    assert missing_ds.is_error is True


def test_write_view_uses_transpiler(kernel: KernelClient, tmp_path: Path) -> None:
    failing = CommandTranspiler(
        [sys.executable, "-c", "import sys; sys.stderr.write('bad jsx'); sys.exit(1)"]
    )
    ex = executor(kernel, tmp_path, transpiler=failing)
    ex.run(ToolCall(id="1", name="run_python", input=MAKE_DF))
    out = ex.run(
        ToolCall(
            id="2",
            name="write_view",
            input={"source": "<", "datasets": ["df"], "initial_state": "{}"},
        )
    )
    assert out.is_error is True and "bad jsx" in out.content
    assert ex.view is None
    ok = executor(kernel, tmp_path)
    good = ok.run(
        ToolCall(
            id="3",
            name="write_view",
            input={
                "source": "export default () => null",
                "datasets": ["df"],
                "initial_state": '{"k": 1}',
            },
        )
    )
    bad_json = ok.run(
        ToolCall(
            id="4",
            name="write_view",
            input={
                "source": "export default () => null",
                "datasets": ["df"],
                "initial_state": "[1]",
            },
        )
    )
    assert bad_json.is_error is True
    assert good.is_error is False
    assert ok.view is not None and ok.view.component_id == "inline"
    assert ok.view.initial_state == {"k": 1}


def test_unknown_tool_and_bad_args(kernel: KernelClient, tmp_path: Path) -> None:
    ex = executor(kernel, tmp_path)
    assert ex.run(ToolCall(id="1", name="fly", input={})).is_error is True
    assert ex.run(ToolCall(id="2", name="run_python", input={})).is_error is True


def test_search_without_dataset_browses_by_tags(kernel: KernelClient, tmp_path: Path) -> None:
    ex = executor(kernel, tmp_path)
    found = ex.run(
        ToolCall(id="1", name="search_components", input={"dataset": "", "tags": ["table"]})
    )
    assert found.is_error is False
    assert [m["id"] for m in json.loads(found.content)] == ["table"]


def test_broken_manifests_do_not_break_render_or_search(
    kernel: KernelClient, tmp_path: Path
) -> None:
    ex = executor(kernel, tmp_path)
    write_broken_components(tmp_path / "lib")
    ex.run(ToolCall(id="1", name="run_python", input=MAKE_DF))
    found = ex.run(
        ToolCall(id="2", name="search_components", input={"dataset": "df", "tags": ["table"]})
    )
    assert [m["id"] for m in json.loads(found.content)] == ["table"]
    rendered = ex.run(
        ToolCall(
            id="3",
            name="render_view",
            input={"component_id": "table", "datasets": ["df"], "initial_state": "{}"},
        )
    )
    assert rendered.is_error is False
    assert ex.view is not None and ex.view.component_id == "table"


class Rejecting:
    def check(self, source: str) -> str | None:
        return f"cannot parse {len(source)} characters"


def test_render_view_checks_the_component_source(kernel: KernelClient, tmp_path: Path) -> None:
    ex = executor(kernel, tmp_path, Rejecting())
    ex.run(ToolCall(id="1", name="run_python", input=MAKE_DF))
    out = ex.run(
        ToolCall(
            id="2",
            name="render_view",
            input={"component_id": "table", "datasets": ["df"], "initial_state": "{}"},
        )
    )
    assert out.is_error is True and "transpile error" in out.content
    assert ex.view is None


def test_search_for_an_unknown_dataset_is_an_error(kernel: KernelClient, tmp_path: Path) -> None:
    out = executor(kernel, tmp_path).run(
        ToolCall(id="1", name="search_components", input={"dataset": "zz", "tags": []})
    )
    assert out.is_error is True and "zz" in out.content


def test_unreadable_component_source_is_a_tool_error(kernel: KernelClient, tmp_path: Path) -> None:
    ex = executor(kernel, tmp_path)
    (tmp_path / "lib" / "table" / "component.tsx").write_bytes(b"\xff\xfe not utf-8")
    ex.run(ToolCall(id="1", name="run_python", input=MAKE_DF))
    out = ex.run(
        ToolCall(
            id="2",
            name="render_view",
            input={"component_id": "table", "datasets": ["df"], "initial_state": "{}"},
        )
    )
    assert out.is_error is True and "table" in out.content
    assert ex.view is None
