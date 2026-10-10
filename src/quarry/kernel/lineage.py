"""Static analysis of step code for dataset reads, writes, and definitions.

Only bindings in module scope are the step's stores. Function, lambda, and comprehension scopes
contribute only their free names as loads. A class body contributes every name it reads, because
class-level names are looked up at run time and can fall through to the module. The body of an
`except ... as name` handler binds in its enclosing scope, but `name` there is the exception, so
loading it is not a read. Assigning to or deleting an attribute or subscript in module scope
(`df.x = ...`, `del df[k]`) changes the object its root name holds, so it stores that name too.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

_ScopeKind = Literal["module", "function", "class", "comprehension"]


@dataclass(slots=True, frozen=True)
class CodeNames:
    stores: frozenset[str]
    loads: frozenset[str]
    defines: frozenset[str]
    # String literals handed to `sql_local(...)` or `<anything>.sql(...)`: DuckDB can name the
    # tables they read, which the executor turns into dataset reads.
    sql_literals: frozenset[str] = frozenset()


def analyze(code: str) -> CodeNames:
    """Collect module-level stores, loads, and definitions.

    `ast.parse` errors propagate unchanged: SyntaxError, or RecursionError or MemoryError for code
    nested deeper than CPython itself can parse. The walk has no depth limit of its own.
    """
    visitor = _ScopeVisitor()
    visitor.walk(ast.parse(code))
    module = visitor.module
    return CodeNames(
        frozenset(module.bound),
        frozenset(module.loads),
        frozenset(visitor.defines),
        frozenset(visitor.sql_literals),
    )


def dataset_writes(names: CodeNames, before: set[str], after: set[str]) -> list[str]:
    """Datasets the code stored, plus new ones it bound invisibly (star import, `global`)."""
    return sorted(n for n in after if n in names.stores or n not in before)


def dataset_reads(names: CodeNames, before: set[str], defined_earlier: set[str]) -> list[str]:
    """Loaded names that were datasets before the step or helpers defined by earlier steps."""
    return sorted(n for n in names.loads if n in before or n in defined_earlier)


@dataclass(slots=True)
class _Scope:
    kind: _ScopeKind
    parent: _Scope | None = None
    bound: set[str] = field(default_factory=set)
    loads: set[str] = field(default_factory=set)
    declared: set[str] = field(default_factory=set)  # `global` / `nonlocal` names
    # Set on an `except ... as alias` handler's body, which shares its parent's kind, `bound`
    # and `declared`: only the alias is its own.
    alias: str | None = None

    def free_names(self) -> set[str]:
        if self.alias is not None:
            return self.loads - {self.alias}
        if self.kind == "class":
            return self.loads
        return self.loads - (self.bound - self.declared)

    def close(self) -> None:
        """Hand this scope's free names to the scope that encloses it."""
        if self.parent is not None:
            self.parent.loads |= self.free_names()


class _ScopeVisitor(ast.NodeVisitor):
    """Walks with an explicit work stack: valid code nests deeper than Python's recursion limit."""

    def __init__(self) -> None:
        self.module = _Scope("module")
        self.defines: set[str] = set()
        self.sql_literals: set[str] = set()
        self._scope = self.module
        self._pending: list[tuple[ast.AST, _Scope] | _Scope] = []

    def walk(self, tree: ast.AST) -> None:
        self._pending.append((tree, self.module))
        while self._pending:
            item = self._pending.pop()
            if isinstance(item, _Scope):
                item.close()
                continue
            node, self._scope = item
            super().visit(node)

    def visit(self, node: ast.AST) -> None:
        # Every handler and generic_visit come through here: defer the node, in the current scope.
        self._pending.append((node, self._scope))

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self._scope.bound.add(node.id)
        elif isinstance(node.ctx, ast.Load):
            self._scope.loads.add(node.id)
        # A `del` target leaves the namespace: it is neither read nor written.

    def visit_Attribute(self, node: ast.Attribute | ast.Subscript) -> None:
        # A target's outermost attribute or subscript is its only Store or Del link, so this one
        # handler sees every form: plain, augmented, annotated, unpacked, `for`, `with`, `del`.
        # At module level `df.columns = ...` or `del df["c"]` changes the object `df` holds, a
        # store of `df`; in a function `df` stays a free name the function reads.
        if isinstance(node.ctx, ast.Store | ast.Del) and self._scope.kind == "module":
            root = _root_name(node)
            if root is not None:
                self._scope.bound.add(root)
        self.generic_visit(node)

    visit_Subscript = visit_Attribute

    def visit_Call(self, node: ast.Call) -> None:
        if node.args and _is_sql_call(node.func):
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                self.sql_literals.add(first.value)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name):
            self._scope.loads.add(node.target.id)  # `c += 1` reads c before rebinding it
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if (
            node.value is None
            and isinstance(node.target, ast.Name)
            and self._scope.kind == "module"
        ):
            self.visit(node.annotation)  # a bare module-level annotation binds nothing
            return
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        # PEP 572: a walrus binds in the nearest enclosing scope that is not a comprehension.
        owner = self._scope
        while owner.kind == "comprehension" and owner.parent is not None:
            owner = owner.parent
        owner.bound.add(node.target.id)
        self.visit(node.value)

    def visit_Import(self, node: ast.Import | ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                self._scope.bound.add(alias.asname or alias.name.split(".")[0])

    visit_ImportFrom = visit_Import

    def visit_Global(self, node: ast.Global | ast.Nonlocal) -> None:
        self._scope.declared.update(node.names)

    visit_Nonlocal = visit_Global

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is None:
            self.generic_visit(node)
            return
        if node.type is not None:
            self.visit(node.type)  # evaluated before the alias is bound
        parent = self._scope
        # Python unbinds the alias when the handler exits, so it is never a module store,
        # but inside a function it is a local everywhere, and reading it is not a free name.
        if parent.kind != "module":
            parent.bound.add(node.name)
        body = _Scope(
            parent.kind, parent, bound=parent.bound, declared=parent.declared, alias=node.name
        )
        self._pending.append(body)  # as in `_visit_scope`
        self._pending.extend((stmt, body) for stmt in node.body)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name is not None:
            self._scope.bound.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self._scope.bound.add(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest is not None:
            self._scope.bound.add(node.rest)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._define(node.name)
        for decorator in node.decorator_list:
            self.visit(decorator)
        self.visit(node.args)  # defaults and annotations are evaluated where the def runs
        if node.returns is not None:
            self.visit(node.returns)
        self._visit_scope("function", node.body, bound=_parameters(node.args))

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._define(node.name)
        for expr in [*node.decorator_list, *node.bases, *node.keywords]:
            self.visit(expr)
        self._visit_scope("class", node.body)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.visit(node.args)
        self._visit_scope("function", [node.body], bound=_parameters(node.args))

    def visit_ListComp(self, node: ast.ListComp | ast.SetComp | ast.GeneratorExp) -> None:
        self._visit_comprehension(node.generators, [node.elt])

    visit_SetComp = visit_GeneratorExp = visit_ListComp

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node.generators, [node.key, node.value])

    def _visit_comprehension(
        self, generators: list[ast.comprehension], results: list[ast.expr]
    ) -> None:
        outermost, *inner = generators
        self.visit(outermost.iter)  # evaluated in the enclosing scope, before the loop starts
        body: list[ast.AST] = [outermost.target, *outermost.ifs, *inner, *results]
        self._visit_scope("comprehension", body)

    def _define(self, name: str) -> None:
        if self._scope.kind == "module":
            self.defines.add(name)
        self._scope.bound.add(name)

    def _visit_scope(
        self, kind: _ScopeKind, body: Iterable[ast.AST], bound: Iterable[str] = ()
    ) -> None:
        scope = _Scope(kind, parent=self._scope, bound=set(bound))
        self._pending.append(scope)  # popped, and closed, only after its whole body is walked
        self._pending.extend((node, scope) for node in body)


def _is_sql_call(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return func.id == "sql_local"
    return isinstance(func, ast.Attribute) and func.attr == "sql"


def _root_name(node: ast.Attribute | ast.Subscript) -> str | None:
    """The name an attribute or subscript chain hangs off; None when it starts at another
    expression, as `f().x` does."""
    value = node.value
    while isinstance(value, ast.Attribute | ast.Subscript):
        value = value.value
    return value.id if isinstance(value, ast.Name) else None


def _parameters(args: ast.arguments) -> set[str]:
    every = [*args.posonlyargs, *args.args, args.vararg, *args.kwonlyargs, args.kwarg]
    return {a.arg for a in every if a is not None}
