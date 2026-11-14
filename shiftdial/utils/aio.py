"""Blocking calls into WinRT's async operations."""
from __future__ import annotations

import asyncio
from typing import Any


def wait(op: Any) -> Any:
    """Run ``op`` (a WinRT IAsyncOperation, or any awaitable) to completion and return its result.

    WinRT operations are awaitable but not coroutines, so asyncio.run() refuses them directly.
    """
    async def go() -> Any:
        return await op

    return asyncio.run(go())
