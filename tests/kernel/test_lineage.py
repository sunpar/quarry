import pytest

from quarry.kernel.lineage import analyze, dataset_reads, dataset_writes


def test_simple_assignment() -> None:
    names = analyze("returns = loaders.daily_returns(['AAPL'])")
    assert names.stores == {"returns"}
    assert "loaders" in names.loads
    assert names.defines == frozenset()


def test_attribute_chain_root_is_a_load() -> None:
    names = analyze("tech = returns.filter(pl.col('sector') == 'tech')")
    assert names.stores == {"tech"}
    assert {"returns", "pl"} <= names.loads


def test_subscript_root_is_a_load() -> None:
    names = analyze("x = frames['a']")
    assert "frames" in names.loads


def test_tuple_unpacking_and_augmented() -> None:
    names = analyze("a, b = f()\nc += 1")
    assert names.stores == {"a", "b", "c"}
    assert {"f", "c"} <= names.loads


def test_with_and_for_targets() -> None:
    names = analyze("with open('x') as fh:\n    pass\nfor row in rows:\n    pass")
    assert {"fh", "row"} <= names.stores
    assert "rows" in names.loads


def test_imports_are_stores() -> None:
    names = analyze("import polars as pl\nfrom datetime import date")
    assert names.stores == {"pl", "date"}


def test_function_definition_and_free_variables() -> None:
    code = "def clean(df):\n    return df.join(sectors, on='ticker')\n"
    names = analyze(code)
    assert names.defines == {"clean"}
    assert "sectors" in names.loads
    assert "df" not in names.loads


def test_function_locals_are_not_loads() -> None:
    code = "def f():\n    tmp = 1\n    return tmp\n"
    assert "tmp" not in analyze(code).loads


def test_syntax_error_propagates() -> None:
    with pytest.raises(SyntaxError):
        analyze("def (:")


def test_dataset_writes_only_counts_dataset_objects() -> None:
    names = analyze("returns = None\nprices = load()")
    writes = dataset_writes(names, before={"returns"}, after={"prices"})
    assert writes == ["prices"]


def test_dataset_writes_includes_rebound_existing_dataset() -> None:
    names = analyze("returns = returns.head(10)")
    assert dataset_writes(names, before={"returns"}, after={"returns"}) == ["returns"]


def test_dataset_reads() -> None:
    names = analyze("out = clean(returns, other)")
    reads = dataset_reads(names, before={"returns", "unused"}, defined_earlier={"clean"})
    assert reads == ["clean", "returns"]


def test_comprehension_and_generator_targets_are_not_stores() -> None:
    names = analyze("total = sum(len(df) for df in frames)")
    assert names.stores == {"total"}
    assert "df" not in names.stores | names.loads
    assert {"sum", "len", "frames"} <= names.loads

    names = analyze("heads = [f.head() for f in frames if f.height]")
    assert names.stores == {"heads"}
    assert "f" not in names.stores | names.loads
    assert "frames" in names.loads

    names = analyze("f = lambda x: x + offset")
    assert names.stores == {"f"}
    assert "offset" in names.loads
    assert "x" not in names.loads


def test_walrus_in_comprehension_binds_module_scope() -> None:
    names = analyze("[y := g(v) for v in vs]")
    assert "y" in names.stores
    assert "v" not in names.stores
    assert {"g", "vs"} <= names.loads


def test_del_is_neither_read_nor_write() -> None:
    names = analyze("del returns")
    assert "returns" not in names.stores | names.loads
    assert dataset_writes(names, before={"returns"}, after=set()) == []


def test_nested_function_locals_are_not_free() -> None:
    names = analyze("def f(xs):\n    def g(y):\n        return y + k\n    return g(xs)\n")
    assert "k" in names.loads
    assert "y" not in names.loads

    names = analyze("def f(xs):\n    return map(lambda v: v + k, xs)\n")
    assert "k" in names.loads
    assert "v" not in names.loads


def test_match_capture_is_a_store() -> None:
    code = (
        "match event:\n"
        "    case {'frame': frame, **rest}:\n"
        "        pass\n"
        "    case [first, *others]:\n"
        "        pass\n"
        "    case Point(x=px) as point:\n"
        "        pass\n"
    )
    names = analyze(code)
    assert names.stores == {"frame", "rest", "first", "others", "px", "point"}
    assert {"event", "Point"} <= names.loads


def test_outermost_comprehension_iterable_is_read_in_enclosing_scope() -> None:
    assert "frame" in analyze("heads = [frame.head() for frame in frame]").loads


def test_except_alias_is_not_a_store() -> None:
    names = analyze("try:\n    x = f()\nexcept ValueError as err:\n    pass\n")
    assert names.stores == {"x"}

    code = "def f():\n    try:\n        pass\n    except ValueError as err:\n        log(err)\n"
    assert "err" not in analyze(code).loads


def test_bare_annotation_is_not_a_store() -> None:
    names = analyze("returns: pl.DataFrame")
    assert names.stores == frozenset()
    assert "pl" in names.loads
    assert analyze("n: int = 1").stores == {"n"}


def test_star_import_and_dotted_import() -> None:
    assert analyze("from helpers import *\nimport os.path").stores == {"os"}


def test_definition_time_expressions_are_loads() -> None:
    code = "@cache\ndef f(x: Frame = default) -> Out:\n    return x\n"
    assert {"cache", "Frame", "default", "Out"} <= analyze(code).loads

    names = analyze("class C(Base, metaclass=Meta):\n    size = limit\n")
    assert names.defines == {"C"}
    assert {"Base", "Meta", "limit"} <= names.loads
    assert "x" in analyze("class C:\n    x = x\n").loads  # the class body reads the module's x


def test_definitions_are_module_scope_bindings() -> None:
    names = analyze("if ok:\n    def helper():\n        pass\n")
    assert names.defines == {"helper"}
    assert "helper" in names.stores

    names = analyze("def outer():\n    def inner():\n        pass\n    return inner\n")
    assert names.defines == {"outer"}
    assert "inner" not in names.loads


def test_global_and_nonlocal_declarations() -> None:
    names = analyze("def f():\n    global returns\n    returns = returns.head()\n")
    assert "returns" in names.loads
    assert "returns" not in names.stores

    code = (
        "def f():\n    n = 0\n    def g():\n        nonlocal n\n        n += step\n    return g\n"
    )
    names = analyze(code)
    assert "step" in names.loads
    assert "n" not in names.loads
