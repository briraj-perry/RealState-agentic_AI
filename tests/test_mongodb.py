import asyncio
import sqlite3
from contextlib import suppress

import pytest
from pymongo.errors import DuplicateKeyError

from estate_ai.db import Audit, ConcurrentWriteError, Customer, Job, Outbox, Property
from estate_ai.migrate_sqlite import migrate
from estate_ai.workflows import Worker


def test_transaction_rolls_back_entire_write_set_on_duplicate(factory):
    with factory() as session:
        session.add(Customer(phone="919876543210"))
        session.commit()
    with factory() as session:
        session.add(Audit(phone="test", action="must_not_commit"))
        session.add(Customer(phone="919876543210"))
        with pytest.raises(DuplicateKeyError):
            session.commit()
    assert factory.database.audit.count_documents({}) == 0


def test_concurrent_changes_conflict_without_overwriting_other_writer(factory):
    with factory() as session:
        session.add(Property(id="p1", title="Original", city="Mohali", bedrooms=3, asking_price=8500000))
        session.commit()
    with factory() as first, factory() as second:
        one, two = first.get(Property, "p1"), second.get(Property, "p1")
        one.title = "Dealer edit"
        first.commit()
        two.asking_price = 8000000
        second.add(Audit(phone="test", action="must_not_commit"))
        with pytest.raises(ConcurrentWriteError):
            second.commit()
    with factory() as session:
        row = session.get(Property, "p1")
        assert row.title == "Dealer edit"
        assert row.asking_price == 8500000
    assert factory.database.audit.count_documents({}) == 0


@pytest.mark.asyncio
async def test_worker_lease_serializes_recovery_and_transfers_on_shutdown(factory, settings):
    ticks, recovered = [0, 0], [0, 0]

    class ObservedWorker(Worker):
        def __init__(self, index):
            super().__init__(factory, settings)
            self.index = index

        def recover(self):
            recovered[self.index] += 1
            super().recover()

        async def tick(self):
            ticks[self.index] += 1

    async def wait_for(predicate):
        async with asyncio.timeout(8):
            while not predicate():
                await asyncio.sleep(0.05)

    tasks = []
    try:
        tasks.append(asyncio.create_task(ObservedWorker(0).run()))
        await wait_for(lambda: ticks[0] > 0)
        tasks.append(asyncio.create_task(ObservedWorker(1).run()))
        await asyncio.sleep(0.7)
        assert ticks[1] == recovered[1] == 0
        tasks[0].cancel()
        with suppress(asyncio.CancelledError):
            await tasks[0]
        previous = ticks[0]
        await wait_for(lambda: ticks[1] > 0)
        assert ticks[0] == previous
        assert recovered == [1, 1]
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task


def test_recovery_preserves_ambiguous_send_and_requeues_processing(factory, settings):
    with factory() as session:
        session.add(Job(id="j1", phone="test", text="hello", channel="simulate", state="processing"))
        session.add(Outbox(id="j1", phone="test", body="reply", channel="whatsapp", state="sending"))
        session.commit()
    Worker(factory, settings).recover()
    with factory() as session:
        assert session.get(Job, "j1").state == "pending"
        assert session.get(Outbox, "j1").state == "delivery_unknown"


def test_legacy_workspace_import_is_read_only_and_idempotent(factory, tmp_path):
    source = tmp_path / "old.db"
    with sqlite3.connect(source) as legacy:
        legacy.execute(
            "CREATE TABLE customers (phone TEXT, name TEXT, paused INTEGER, opted_out INTEGER, last_inbound REAL)"
        )
        legacy.execute("INSERT INTO customers VALUES ('919876543210', 'Buyer', 0, 0, 1)")
    before = source.read_bytes()
    assert migrate(source, factory) == {"imported": 1, "existing": 0}
    with factory() as session:
        session.get(Customer, "919876543210").name = "Updated in MongoDB"
        session.commit()
    assert migrate(source, factory) == {"imported": 0, "existing": 1}
    with factory() as session:
        assert session.get(Customer, "919876543210").name == "Updated in MongoDB"
    assert source.read_bytes() == before
