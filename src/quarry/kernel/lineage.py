"""Static analysis of step code for dataset reads, writes, and definitions.

Only bindings in module scope are the step's stores. Function, lambda, and comprehension scopes
contribute only their free names as loads. A class body contributes every name it reads, because
class-level names are looked up at run time and can fall through to the module.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal


@dataclass(slots=True, frozen=True)
class CodeNames:
    stores: frozenset[str]
    loads: frozenset[str]
    defines: frozenset[str]


def analyze(code: str) -> CodeNames:
    """Collect module-level stores, loads, and definitions; a SyntaxError propagates."""
    visitor = _ScopeVisitor()
    visitor.visit(ast.parse(code))
    module = visitor.module
    return CodeNames(frozenset(module.bound), frozenset(module.loads), frozenset(visitor.defines))


def dataset_writes(names: CodeNames, before: set[str], after: set[str]) -> list[str]:
    """Datasets the code stored, plus new ones it bound invisibly (star import, `global`)."""
    return sorted(n for n in after if n in names.stores or n not in before)


def dataset_reads(names: CodeNames, before: set[str], defined_earlier: set[str]) -> list[str]:
    """Loaded names that were datasets before the step or helpers defined by earlier steps."""
    return sorted(n for n in names.loads if n in before or n in defined_earlier)


@dataclass(slots=True)
class _Scope:
    kind: Literal["module", "function", "class", "comprehension"]
    bound: set[str] = field(default_factory=set)
    loads: set[str] = field(default_factory=set)
    declared: set[str] = field(default_factory=set)  # `global` / `nonlocal` names

    def free_names(self) -> set[str]:
        if self.kind == "class":
            return self.loads
        return self.loads - (self.bound - self.declared)


class _ScopeVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.module = _Scope("module")
        self.defines: set[str] = set()
        self._scopes = [self.module]

    @property
    def _scope(self) -> _Scope:
        return self._scopes[-1]

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self._scope.bound.add(node.id)
        elif isinstance(node.ctx, ast.Load):
            self._scope.loads.add(node.id)
        # A `del` target leaves the namespace: it is neither read nor written.

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name):
            self._scope.loads.add(node.target.id)  # `c += 1` reads c before rebinding it
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is None and isinstance(node.target, ast.Name) and self._scope is self.module:
            self.visit(node.annotation)  # a bare module-level annotation binds nothing
            return
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        # PEP 572: a walrus binds in the nearest enclosing scope that is not a comprehension.
        owner = next(s for s in reversed(self._scopes) if s.kind != "comprehension")
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
        # Python unbinds the alias when the handler exits, so it is never a module store,
        # but inside a function it is a local and reading it is not a free name.
        if node.name is not None and self._scope is not self.module:
            self._scope.bound.add(node.name)
        self.generic_visit(node)

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
        self._visit_scope(_Scope("function", bound=_parameters(node.args)), node.body)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._define(node.name)
        for expr in [*node.decorator_list, *node.bases, *node.keywords]:
            self.visit(expr)
        self._visit_scope(_Scope("class"), node.body)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.visit(node.args)
        self._visit_scope(_Scope("function", bound=_parameters(node.args)), [node.body])

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
        self._visit_scope(_Scope("comprehension"), body)

    def _define(self, name: str) -> None:
        if self._scope is self.module:
            self.defines.add(name)
        self._scope.bound.add(name)

    def _visit_scope(self, scope: _Scope, body: Iterable[ast.AST]) -> None:
        self._scopes.append(scope)
        for node in body:
            self.visit(node)
        self._scopes.pop()
        self._scope.loads |= scope.free_names()


def _parameters(args: ast.arguments) -> set[str]:
    every = [*args.posonlyargs, *args.args, args.vararg, *args.kwonlyargs, args.kwarg]
    return {a.arg for a in every if a is not None}
