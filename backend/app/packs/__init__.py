"""Product packs: one engine, one YAML file of attributes per product type."""

from functools import lru_cache
from importlib import resources
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

ValueType = Literal["money", "percent", "count", "text", "days", "date"]


class AttributeSpec(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    label: str
    category: str
    value_type: ValueType
    importance: int = Field(ge=1, le=5)
    mitc_required: bool = False
    keywords: list[str] = Field(min_length=1)


class Pack(BaseModel):
    pack: str
    label: str
    # Wording used by prompts, findings and the checklist, so one engine serves every pack.
    subject: str = "an Indian credit card"  # "You extract factual claims about {subject}"
    issuer: str = "the bank"  # who publishes the official terms
    terms_doc: str = "MITC"  # the issuer's authoritative terms document
    prompt_version: str = "cc-extract-v2"  # part of the extraction cache key; bump on change
    notice_rules: bool = True  # RBI's one-month notice for changes in card charges applies
    extract_notes: list[str] = Field(default_factory=list)  # pack-specific extraction rules
    attributes: list[AttributeSpec]

    @field_validator("attributes")
    @classmethod
    def unique_keys(cls, v: list[AttributeSpec]) -> list[AttributeSpec]:
        keys = [a.key for a in v]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate attribute keys")
        return v

    def get(self, key: str) -> AttributeSpec | None:
        return next((a for a in self.attributes if a.key == key), None)

    @property
    def keys(self) -> list[str]:
        return [a.key for a in self.attributes]


@lru_cache
def load_pack(name: str = "credit_card") -> Pack:
    text = resources.files(__package__).joinpath(f"{name}.yaml").read_text(encoding="utf-8")
    return Pack.model_validate(yaml.safe_load(text))


async def sync_pack(session: "AsyncSession", pack: Pack) -> None:
    """Upsert the pack's attributes into the `attribute` table (claims reference it by FK)."""
    from sqlalchemy.dialects.postgresql import insert

    from app.models import Attribute

    rows = [
        {
            "key": a.key,
            "pack": pack.pack,
            "label": a.label,
            "category": a.category,
            "unit": a.value_type,
            "importance": a.importance,
            "mitc_required": a.mitc_required,
        }
        for a in pack.attributes
    ]
    stmt = insert(Attribute).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Attribute.key],
        set_={
            c: stmt.excluded[c]
            for c in ("pack", "label", "category", "unit", "importance", "mitc_required")
        },
    )
    await session.execute(stmt)
