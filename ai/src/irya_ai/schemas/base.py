"""Shared base model for every schema in the AI pipeline."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model with snake_case attributes and camelCase JSON aliases.

    ``Utterance(start_ms=0)`` and ``Utterance.model_validate({"startMs": 0})``
    both work. Use ``model_dump(by_alias=True)`` when sending data to the
    backend or frontend, which follow the camelCase convention of
    ``API_Specification.md``.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )
