import pytest

import service


@pytest.mark.skip(reason="TODO: implementar retrain")
def test_run():
    assert service.run({})
