from quarry.components.library import ComponentLibrary, builtin_root


def test_builtin_library_lists_stage3_components() -> None:
    library = ComponentLibrary([builtin_root()])
    ids = {entry.manifest.id for entry in library.entries()}
    assert {"data-table", "time-series"} <= ids
    table = library.get("data-table")
    assert table is not None
    assert "export default" in table.source_path.read_text()
