import os
from uuid import uuid4

import pytest

from estate_ai.config import Settings
from estate_ai.db import connect


@pytest.fixture
def settings():
    return Settings(
        _env_file=None, admin_api_key="test-admin-secret", worker_enabled=False, allow_demo_data=True
    )


@pytest.fixture
def factory():
    uri = os.environ.get("TEST_MONGODB_URI", "mongodb://127.0.0.1:27019/?replicaSet=rs0")
    # Unique disposable test database; never use the app's configured database.
    result = connect(uri, "estate_test_" + uuid4().hex)
    try:
        yield result
    finally:
        result.client.drop_database(result.database.name)
        result.close()
