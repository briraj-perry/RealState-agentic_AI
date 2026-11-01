import pytest

from estate_ai.config import Settings
from estate_ai.db import connect


@pytest.fixture
def settings():
    return Settings(
        _env_file=None, admin_api_key="test-admin-secret", worker_enabled=False, allow_demo_data=True
    )


@pytest.fixture
def factory(tmp_path):
    return connect("sqlite:///" + str(tmp_path / "test.db"))
