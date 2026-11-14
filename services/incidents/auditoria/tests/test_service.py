import pytest

import service


@pytest.mark.skip(reason="TODO: implementar auditoria")
def test_run():
    assert service.run({})
