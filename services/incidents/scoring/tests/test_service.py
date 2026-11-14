import pytest

import service


@pytest.mark.skip(reason="TODO: implementar scoring")
def test_run():
    assert service.run({})
