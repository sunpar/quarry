"""Failure handling shared by the kernel and the data layer its namespace is built from."""

from __future__ import annotations

from typing import Final

# Kernel-level exits and interrupts: a guard that turns failures into results lets these through.
NOT_FAILURES: Final = (KeyboardInterrupt, SystemExit, GeneratorExit)


def exception_message(exc: BaseException) -> str:
    """`str(exc)`, or a placeholder when the exception cannot print itself."""
    try:
        return str(exc)
    except NOT_FAILURES:
        raise
    except BaseException:  # step code's or a firm library's exception can fail in its __str__
        return f"<unprintable {type(exc).__name__}>"
