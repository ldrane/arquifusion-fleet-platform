"""notify_push: punto de entrada de la Lambda (RF-10.2, MH-MC-02).

Handler delgado: fija el correlation_id (#27), arma las dependencias reales (secreto de la SA, certificados de
Google, Firestore/FCM REST) y delega en service.py.
"""

import json
import os
import time

import gcp_auth
import gcp_rest
import service
from arquifusion_shared import correlation
from arquifusion_shared.observability import logger, tracer

CERTS_MAX_AGE_S = 3600

_cache: dict = {}


def _sa() -> dict:  # pragma: no cover - requiere AWS
    from aws_lambda_powertools.utilities import parameters

    return json.loads(parameters.get_secret(os.environ["GCP_SA_SECRET_NAME"], max_age=300))


def _token() -> str:  # pragma: no cover - requiere GCP
    if "tokens" not in _cache:
        _cache["tokens"] = gcp_auth.TokenSource(gcp_rest.SCOPES)
    return _cache["tokens"].token(_sa())


def _google_keys() -> dict:  # pragma: no cover - red
    if time.time() - _cache.get("certs_at", 0) > CERTS_MAX_AGE_S:
        _, jwks = gcp_rest.http_request("GET", service.CERTS_URL, None, {})
        _cache["certs"] = service.parse_jwks(jwks)
        _cache["certs_at"] = time.time()
    return _cache["certs"]


def _verify(token: str) -> dict:  # pragma: no cover - requiere AWS
    email = os.environ.get("PUSH_SA_EMAIL") or f"pubsub-push@{_sa()['project_id']}.iam.gserviceaccount.com"
    return service.verify_oidc(
        token,
        audience=os.environ.get("PUSH_AUDIENCE", service.DEFAULT_AUDIENCE),
        email=email,
        keys=_google_keys(),
        verify_rs256=gcp_auth.verify_rs256,
    )


DEPS = {
    "verify": _verify,
    "users": lambda: gcp_rest.FirestoreRestUsers(_sa()["project_id"], _token),
    "send": lambda: gcp_rest.FcmRestSender(_sa()["project_id"], _token),
}


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event, context):
    logger.set_correlation_id(correlation.from_any(event))
    return service.run(event, DEPS)
