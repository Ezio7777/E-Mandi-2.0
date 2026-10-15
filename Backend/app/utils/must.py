"""Narrowing helper for rows that must exist at this point (locked re-reads, rows just inserted). Raising NotFoundError keeps a
vanished row a clean 404-style error instead of an AttributeError on None."""
from typing import TypeVar

from app.core.errors import NotFoundError

T = TypeVar("T")


def must(value: T | None, what: str = "Record") -> T:
    if value is None:
        raise NotFoundError(f"{what} not found")
    return value
