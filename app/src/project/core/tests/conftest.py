from collections.abc import Generator

import pytest


@pytest.fixture
def some() -> Generator[int]:
    # setup code
    yield 1
    # teardown code
