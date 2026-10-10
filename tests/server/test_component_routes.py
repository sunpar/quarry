import shutil
from pathlib import Path

import pytest

from quarry.components.library import builtin_root
from tests.agent.test_transpile import STATIC
from tests.server.test_app import make_client, wait_idle

SOURCE = (
    'import { useQuery } from "@quarry/hooks";\n'
    "export default function V({ datasets }: { datasets: string[] }) "
    "{ return <p>{datasets[0]}</p>; }\n"
)


def test_save_component_writes_manifest_and_lists_it(tmp_path: Path) -> None:
    with make_client(tmp_path, []) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(
            f"/sessions/{sid}/steps/manual", json={"code": "df = pl.DataFrame({'d': [1.5]})"}
        )
        wait_idle(client, sid)
        body = {
            "id": "my-view",
            "name": "My view",
            "description": "one column",
            "tags": ["custom"],
            "source": SOURCE,
            "session_id": sid,
            "dataset": "df",
        }
        created = client.post("/components", json=body)
        assert created.status_code == 201, created.text
        manifest = created.json()
        assert manifest["origin"] == "generated"
        assert manifest["schema"]["requires"] == [{"role": "numeric", "dtype": "numeric", "min": 1}]
        assert (tmp_path / "components" / "my-view" / "component.tsx").read_text() == SOURCE
        listed = client.get("/components").json()
        assert "my-view" in {m["id"] for m in listed}
        assert client.post("/components", json=body).status_code == 409
        assert client.post("/components", json={**body, "id": "data-table"}).status_code == 409
        assert not (tmp_path / "components" / "data-table").exists()
        assert client.post("/components", json={**body, "id": "Bad Id"}).status_code == 400
        missing = client.post("/components", json={**body, "id": "nods", "dataset": "nope"})
        assert missing.status_code == 404
        assert not (tmp_path / "components" / "nods").exists()
        unknown = client.post("/components", json={**body, "id": "nosess", "session_id": "nope"})
        assert unknown.status_code == 404
        assert not (tmp_path / "components" / "nosess").exists()


@pytest.mark.skipif(
    not (STATIC / "transpile-check.mjs").exists() or shutil.which("node") is None,
    reason="the transpile check needs the web build and node",
)
def test_save_component_refuses_source_that_does_not_transpile(tmp_path: Path) -> None:
    with make_client(tmp_path, []) as client:
        body = {"id": "broken", "name": "Broken", "source": "export default ("}
        broken = client.post("/components", json=body)
        assert broken.status_code == 400 and "transpile" in broken.json()["detail"]
        assert not (tmp_path / "components" / "broken").exists()


def test_builtin_root_has_the_ids_the_tests_rely_on() -> None:
    assert (builtin_root() / "data-table" / "manifest.json").exists()
