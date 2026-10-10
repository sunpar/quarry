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
        again = client.post("/components", json={**body, "source": "export default 1;\n"})
        assert again.status_code == 409
        assert (tmp_path / "components" / "my-view" / "component.tsx").read_text() == SOURCE
        assert client.post("/components", json={**body, "id": "data-table"}).status_code == 409
        assert not (tmp_path / "components" / "data-table").exists()
        assert client.post("/components", json={**body, "id": "Bad Id"}).status_code == 400
        missing = client.post("/components", json={**body, "id": "nods", "dataset": "nope"})
        assert missing.status_code == 404
        assert not (tmp_path / "components" / "nods").exists()
        unknown = client.post("/components", json={**body, "id": "nosess", "session_id": "nope"})
        assert unknown.status_code == 404
        assert not (tmp_path / "components" / "nosess").exists()


# A folder the library skips: a misspelled key, or an id that is not the folder's name.
@pytest.mark.parametrize(
    "manifest",
    [
        '{"id": "hand", "name": "Hand", "description": "", "tagz": [], '
        '"origin": "generated", "created_at": ""}',
        '{"id": "other", "name": "Hand", "description": "", '
        '"origin": "generated", "created_at": ""}',
    ],
)
def test_save_component_leaves_an_existing_folder_alone(tmp_path: Path, manifest: str) -> None:
    folder = tmp_path / "components" / "hand"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(manifest)
    (folder / "component.tsx").write_text("export default function Mine() { return null }")
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    with make_client(tmp_path, []) as client:
        saved = client.post("/components", json={"id": "hand", "name": "Hand", "source": SOURCE})
        assert saved.status_code == 409, saved.text
        assert "folder" in saved.json()["detail"]
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before


def test_save_component_needs_session_and_dataset_together(tmp_path: Path) -> None:
    with make_client(tmp_path, []) as client:
        body = {"id": "half", "name": "Half", "source": SOURCE}
        assert client.post("/components", json={**body, "session_id": "s"}).status_code == 422
        assert client.post("/components", json={**body, "dataset": "df"}).status_code == 422
    assert not (tmp_path / "components" / "half").exists()


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
