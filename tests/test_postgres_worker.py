"""Real PostgreSQL leadership/rollover check (CI supplies an isolated test database)."""

import asyncio
import os
from contextlib import suppress
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from estate_ai.db import Base
from estate_ai.workflows import Worker


@pytest.mark.asyncio
async def test_postgres_elects_one_worker_and_transfers_after_shutdown(settings):
    url = os.environ.get("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL not set; PostgreSQL integration runs in CI")
    schema = "worker_test_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    ticks = [0, 0]
    recovered = [0, 0]

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
        old_ticks = ticks[0]
        await wait_for(lambda: ticks[1] > 0)
        assert ticks[0] == old_ticks
        assert recovered == [1, 1]
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()
