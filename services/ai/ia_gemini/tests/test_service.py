import pytest

import service


@pytest.mark.skip(reason="TODO: implementar ia_gemini")
def test_run():
    assert service.run({})
