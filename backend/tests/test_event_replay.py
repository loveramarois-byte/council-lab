import asyncio

from app.models import RunEvent
from app.store import Store


def event(run_id: str, event_type: str) -> RunEvent:
    return RunEvent(
        event_id=f"{run_id}-{event_type}",
        run_id=run_id,
        type=event_type,
        stage="test",
        message=event_type,
        progress=50,
    )


async def test_run_events_are_persisted_and_replayed_in_order(tmp_path):
    path = tmp_path / "council.sqlite3"
    store = Store(path)
    first = await store.publish(event("run-1", "run_created"))
    second = await store.publish(event("run-1", "agent_turn_completed"))

    assert first.sequence > 0
    assert second.sequence > first.sequence
    assert [item.type for item in await store.list_events("run-1")] == [
        "run_created",
        "agent_turn_completed",
    ]
    store.close()

    reopened = Store(path)
    assert [item.sequence for item in await reopened.list_events("run-1")] == [
        first.sequence,
        second.sequence,
    ]
    assert [item.type for item in await reopened.list_events("run-1", after_sequence=first.sequence)] == [
        "agent_turn_completed"
    ]
    reopened.close()


async def test_independent_event_waiters_receive_the_same_event(tmp_path):
    store = Store(tmp_path / "council.sqlite3")
    first_waiter = asyncio.create_task(store.wait_for_events("run-2", after_sequence=0, timeout=1))
    second_waiter = asyncio.create_task(store.wait_for_events("run-2", after_sequence=0, timeout=1))
    await asyncio.sleep(0)

    published = await store.publish(event("run-2", "question_analyzed"))
    first, second = await asyncio.gather(first_waiter, second_waiter)

    assert [item.sequence for item in first] == [published.sequence]
    assert [item.sequence for item in second] == [published.sequence]
    store.close()


async def test_event_stream_limit_is_per_run_and_released(tmp_path):
    store = Store(tmp_path / "council.sqlite3")

    assert await store.try_open_event_stream("run-3", limit=2)
    assert await store.try_open_event_stream("run-3", limit=2)
    assert not await store.try_open_event_stream("run-3", limit=2)
    assert await store.try_open_event_stream("another-run", limit=2)

    await store.close_event_stream("run-3")
    assert await store.try_open_event_stream("run-3", limit=2)
    store.close()
