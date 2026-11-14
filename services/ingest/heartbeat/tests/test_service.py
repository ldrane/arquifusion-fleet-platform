import pytest

import service


@pytest.mark.skip(reason="TODO: implementar heartbeat")
def test_run():
    assert service.run({})
