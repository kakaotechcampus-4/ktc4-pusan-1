import asyncio

import pytest
from livekit import agents, rtc


def test_livekit_sdk_is_importable() -> None:
    assert agents is not None
    assert rtc is not None


@pytest.mark.asyncio
async def test_async_test_environment() -> None:
    assert asyncio.get_running_loop().is_running()
