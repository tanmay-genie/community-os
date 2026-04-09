"""
orchestrator/adapters/base.py — Abstract adapter interface.
All tool integrations (Jira, CRM, Calendar, etc.) must implement this.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class AdapterResult:
    success: bool
    output: dict[str, Any]
    error: str | None = None


class BaseAdapter(ABC):
    """
    Abstract base class for all T2T tool adapters.

    Every adapter must implement:
      execute()    — performs the action
      compensate() — undoes the action (for rollback)
    """
    name: str = "base"

    @abstractmethod
    async def execute(self, params: dict[str, Any]) -> AdapterResult:
        """Execute the step action. Must be idempotent."""
        ...

    @abstractmethod
    async def compensate(self, params: dict[str, Any]) -> AdapterResult:
        """Undo the action. Called during rollback."""
        ...


# ── Adapter Registry ──────────────────────────────────────────────────────────

_REGISTRY: dict[str, BaseAdapter] = {}


def register_adapter(adapter: BaseAdapter) -> None:
    _REGISTRY[adapter.name] = adapter


def get_adapter(name: str) -> BaseAdapter | None:
    return _REGISTRY.get(name)


def list_adapters() -> list[str]:
    return list(_REGISTRY.keys())
