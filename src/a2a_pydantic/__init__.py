from typing import TYPE_CHECKING, Any

from a2a_pydantic import v03, v10
from a2a_pydantic.converters import convert_to_v03
from a2a_pydantic.converters_v10 import convert_to_v10

__all__ = [
    "v03",
    "v10",
    "convert_to_v03",
    "convert_to_v10",
    "convert_to_proto",
    "convert_from_proto",
]


if TYPE_CHECKING:
    from a2a_pydantic.from_proto import convert_from_proto as convert_from_proto
    from a2a_pydantic.to_proto import convert_to_proto as convert_to_proto


def __getattr__(name: str) -> Any:
    if name == "convert_to_proto":
        from a2a_pydantic.to_proto import convert_to_proto

        globals()["convert_to_proto"] = convert_to_proto
        return convert_to_proto
    if name == "convert_from_proto":
        from a2a_pydantic.from_proto import convert_from_proto

        globals()["convert_from_proto"] = convert_from_proto
        return convert_from_proto
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
