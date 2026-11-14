from unittest.mock import MagicMock

import pytest
import requests

from simulator.sender import SendError, TelemetrySender, batches


def _resp(status):
    r = MagicMock(status_code=status, text="")
    return r


def _sender(*responses):
    session = MagicMock()
    session.post.side_effect = list(responses)
    sleeps = []
    return TelemetrySender("https://api.test/v1/", "k", session=session, sleep=sleeps.append), session, sleeps


def test_batches_respect_contract_limit():
    sizes = [len(b) for b in batches(range(250))]
    assert sizes == [100, 100, 50]
    with pytest.raises(ValueError):
        list(batches([], size=101))


def test_send_uses_api_key_and_correlation_id():
    sender, session, _ = _sender(_resp(202))
    sender.send([{"machine_id": "EX-001"}])
    _, kwargs = session.post.call_args
    assert session.post.call_args.args[0] == "https://api.test/v1/telemetry"
    assert kwargs["headers"]["x-api-key"] == "k"
    assert kwargs["headers"]["X-Correlation-Id"]
    assert kwargs["json"] == {"readings": [{"machine_id": "EX-001"}]}


def test_retries_on_429_5xx_and_network_errors():
    sender, session, sleeps = _sender(_resp(429), requests.ConnectionError("x"), _resp(503), _resp(202))
    sender.send_batch([{}])
    assert session.post.call_count == 4
    assert len(sleeps) == 3 and sleeps == sorted(sleeps)


def test_does_not_retry_client_errors():
    sender, session, _ = _sender(_resp(400))
    with pytest.raises(SendError, match="HTTP 400"):
        sender.send_batch([{}])
    assert session.post.call_count == 1


def test_gives_up_after_max_retries():
    sender, session, _ = _sender(*[_resp(500)] * 6)
    with pytest.raises(SendError, match="agotados"):
        sender.send_batch([{}])
    assert session.post.call_count == 6


def test_requires_credentials():
    with pytest.raises(ValueError):
        TelemetrySender("", "")
