import pytest

import service


@pytest.mark.skip(reason="TODO: implementar correlacion")
def test_run():
    assert service.run({})
