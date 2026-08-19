"""Shared response + pagination models used across routers."""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageParams(BaseModel):
    """Query params for paginated endpoints (FR-18: bound response size)."""

    page: int = Field(default=1, ge=1, description="1-based page number.")
    page_size: int = Field(
        default=50, ge=1, le=500, description="Items per page (capped)."
    )

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page(BaseModel, Generic[T]):
    """Envelope for a page of results."""

    items: list[T]
    page: int
    page_size: int
    total: int = Field(..., description="Total items across all pages.")

    @property
    def has_next(self) -> bool:
        return self.page * self.page_size < self.total
