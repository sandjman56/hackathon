import pytest

from tests.fixtures.eis.build_sample import build_sample_eis_bytes


@pytest.fixture(scope="session")
def sample_eis_bytes() -> bytes:
    return build_sample_eis_bytes()
