from a2a_pydantic.base import _ONE_OF_FIELDS
from a2a_pydantic.v10 import models as _models
from a2a_pydantic.v10.models import *  # noqa: F401,F403

# v1.0 spec pins the following as "exactly one of" unions that the proto-derived
# JSON Schema leaves as flat optional fields. Register them so A2ABaseModel's
# _enforce_one_of validator fires at construction time.
_ONE_OF_FIELDS.update(
    {
        _models.Part: ("text", "raw", "url", "data"),
        _models.SecurityScheme: (
            "api_key_security_scheme",
            "http_auth_security_scheme",
            "oauth2_security_scheme",
            "open_id_connect_security_scheme",
            "mtls_security_scheme",
        ),
        _models.OAuthFlows: (
            "authorization_code",
            "client_credentials",
            "implicit",
            "password",
            "device_code",
        ),
        _models.SendMessageResponse: ("task", "message"),
        _models.StreamResponse: (
            "task",
            "message",
            "status_update",
            "artifact_update",
        ),
    }
)
