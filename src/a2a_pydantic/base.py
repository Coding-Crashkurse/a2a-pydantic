from pydantic import BaseModel, ConfigDict, model_validator
from pydantic.alias_generators import to_camel


def to_camel_custom(snake: str) -> str:
    """Convert a snake_case string to camelCase.

    Args:
        snake: The string to convert.

    Returns:
        The converted camelCase string.
    """
    # First, remove any trailing underscores. This is common for names that
    # conflict with Python keywords, like 'in_' or 'from_'.
    if snake.endswith("_"):
        snake = snake.rstrip("_")
    return to_camel(snake)


# Registry of A2A v1.0 classes that must enforce an "exactly one of"
# constraint across a subset of their fields. Populated by
# ``a2a_pydantic.v10.__init__`` at import time.
#
# Keyed on class identity (not class name) so that v0.3 twins of same-named
# types (e.g. ``OAuthFlows`` exists in both versions) do NOT accidentally
# inherit v1.0's stricter validation — v0.3's JSON Schema does not impose
# the same one-of constraint and its model is generated accordingly.
_ONE_OF_FIELDS: dict[type, tuple[str, ...]] = {}


class A2ABaseModel(BaseModel):
    """Base class for shared behavior across A2A data models.

    Provides a common configuration (alias-based population, camelCase
    wire format) and a generic "exactly one of" validator that fires for
    classes listed in :data:`_ONE_OF_FIELDS`. The one-of validator is
    needed because the A2A v1.0 proto-derived JSON Schema models its
    discriminated unions as flat optional fields (e.g. ``Part`` has
    ``text``, ``raw``, ``url``, ``data`` all as ``Optional``), which
    ``datamodel-codegen`` cannot turn into a real one-of on its own.
    """

    model_config = ConfigDict(
        # SEE: https://docs.pydantic.dev/latest/api/config/#pydantic.config.ConfigDict.populate_by_name
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        alias_generator=to_camel_custom,
        # Re-validate on attribute assignment so `task.metadata = {"a": 1}`
        # is coerced back to the declared type (e.g. Struct) instead of
        # silently storing a plain dict that later crashes convert_to_v03.
        validate_assignment=True,
    )

    @model_validator(mode="after")
    def _enforce_one_of(self):
        fields = _ONE_OF_FIELDS.get(type(self))
        if fields is None:
            return self
        populated = tuple(f for f in fields if getattr(self, f) is not None)
        if len(populated) != 1:
            raise ValueError(
                f"{type(self).__name__} must set exactly one of "
                f"{list(fields)}, got {list(populated) or 'none'}"
            )
        return self
