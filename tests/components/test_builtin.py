from quarry.components.library import ComponentLibrary, builtin_root

BUILTIN_IDS = {
    "data-table",
    "data-table-tanstack",
    "time-series",
    "ohlc",
    "bar-line",
    "scatter",
    "heatmap",
    "large-series",
    "pivot",
}


def test_builtin_library_lists_every_spec_component() -> None:
    library = ComponentLibrary([builtin_root()])
    assert {e.manifest.id for e in library.entries()} == BUILTIN_IDS
    for entry in library.entries():
        assert "export default" in entry.source_path.read_text()
