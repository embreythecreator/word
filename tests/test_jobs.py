from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from open_notebook import jobs


@pytest.mark.asyncio
async def test_submit_command_enqueues_without_worker(monkeypatch):
    deferred = AsyncMock(return_value=42)

    class FakeDeferrer:
        async def defer_async(self, **kwargs):
            return await deferred(**kwargs)

    class FakeApp:
        def configure_task(self, name, allow_unknown=False):
            assert name == "open_notebook.embed_note"
            assert allow_unknown is False
            return FakeDeferrer()

    @asynccontextmanager
    async def fake_opened_app():
        yield FakeApp()

    mirror_update = AsyncMock()
    monkeypatch.setattr(jobs, "_opened_app", fake_opened_app)
    monkeypatch.setattr(jobs, "_upsert_command_record", mirror_update)

    command_id = await jobs.submit_command(
        "open_notebook",
        "embed_note",
        {"note_id": "note:test"},
    )

    assert command_id == "command:42"
    deferred.assert_awaited_once_with(note_id="note:test")
    mirror_update.assert_awaited_once_with(
        command_id="command:42",
        app_id="open_notebook",
        name="embed_note",
        status="queued",
        input_data={"note_id": "note:test"},
    )
