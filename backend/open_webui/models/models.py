from __future__ import annotations

import json
import logging
import time
from typing import Optional

from open_webui.internal.db import Base, JSONField, get_async_db_context
from open_webui.model_catalogue import CATALOGUE_USER_ID, MODEL_CATALOGUE
from open_webui.models.access_grants import AccessGrantModel, AccessGrants
from open_webui.models.groups import Groups
from open_webui.models.users import User, UserModel, UserResponse, Users
from open_webui.utils.validate import validate_profile_image_url
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import BigInteger, Boolean, Column, String, Text, cast, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

# Track invalid profile_image_url values we've already warned about so we
# don't flood the logs on every DB read (the validator fires per-row).
_warned_profile_urls: set[str] = set()


# --- Models DB Schema ---


class ModelParams(BaseModel):
    """Parameters for model inference (temperature, top_p, etc.)."""

    model_config = ConfigDict(extra='allow')


class ModelMeta(BaseModel):
    """Metadata for a workspace model entry (profile, description, tags, capabilities)."""

    profile_image_url: str | None = None
    description: str | None = Field(default=None, description='User-facing description of the model.')
    capabilities: dict | None = None

    model_config = ConfigDict(extra='allow')

    @field_validator('profile_image_url', mode='before')
    @classmethod
    def check_profile_image_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            return validate_profile_image_url(v)
        except ValueError:
            if v not in _warned_profile_urls:
                _warned_profile_urls.add(v)
                log.warning(
                    'Clearing invalid profile_image_url stored in DB (likely a legacy SVG data-URI): %.80s…',
                    v,
                )
            return None

    @model_validator(mode='before')
    @classmethod
    def normalize_tags(cls, data):
        if isinstance(data, dict) and 'tags' in data:
            raw_tags = data['tags']
            if isinstance(raw_tags, list):
                normalized = []
                for tag in raw_tags:
                    if isinstance(tag, str):
                        normalized.append({'name': tag})
                    elif isinstance(tag, dict) and 'name' in tag:
                        normalized.append(tag)
                data['tags'] = normalized
        return data


class Model(Base):
    """Workspace model entry — wraps an upstream LLM with custom params and metadata."""

    __tablename__ = 'model'

    id = Column(Text, primary_key=True, unique=True)  # API model identifier; overrides built-in when matching
    user_id = Column(Text)  # owner
    base_model_id = Column(Text, nullable=True)  # actual upstream model for proxied requests
    name = Column(Text)  # human-readable display name
    params = Column(JSONField)  # see ModelParams
    meta = Column(JSONField)  # see ModelMeta
    is_active = Column(Boolean, default=True)  # soft-disable toggle
    updated_at = Column(BigInteger)  # epoch seconds
    created_at = Column(BigInteger)  # epoch seconds


class ModelModel(BaseModel):
    id: str
    user_id: str
    base_model_id: str | None = None

    name: str
    params: ModelParams
    meta: ModelMeta

    access_grants: list[AccessGrantModel] = Field(default_factory=list)

    is_active: bool
    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch

    model_config = ConfigDict(
        from_attributes=True,
    )


class ModelUserResponse(ModelModel):
    user: UserResponse | None = None


class ModelAccessResponse(ModelUserResponse):
    write_access: bool | None = False


class ModelResponse(ModelModel):
    pass


class ModelListResponse(BaseModel):
    items: list[ModelUserResponse]
    total: int


class ModelAccessListResponse(BaseModel):
    items: list[ModelAccessResponse]
    total: int


class ModelForm(BaseModel):
    model_config = ConfigDict(extra='ignore')

    id: str
    base_model_id: str | None = None
    name: str
    meta: ModelMeta
    params: ModelParams
    access_grants: list[dict | None] = None
    is_active: bool = True


# Sunway: models are CODE, not rows (hardening plan Item 9). Every read below resolves against
# `model_catalogue.py`; the `model` table is no longer a source and the write methods are gone
# along with the routes that called them.
#
# Why the whole table and not just the two hot call sites: `get_model_by_id` alone had twelve
# callers, including the completion path. Swapping the source inside ModelsTable means every
# caller keeps working unchanged and none can accidentally keep reading rows.
#
# ACCESS GRANTS. Every catalogue model carries a synthetic wildcard READ grant. Grants used to
# live in a separate table, and the plan flagged the failure mode: lose the `principal_id: "*"`
# row and EVERY model becomes inaccessible. A grant that cannot go missing cannot cause that.
# There is deliberately no write grant -- a code-defined model is not editable at runtime by
# anyone. Per-group model scoping is not supported and is not wanted: all tenants get the same
# models, which is the premise that makes the catalogue possible at all.
_CATALOGUE_CACHE: list[ModelModel] | None = None


def _catalogue_read_grant(model_id: str) -> AccessGrantModel:
    return AccessGrantModel(
        id=f'catalogue:{model_id}',
        resource_type='model',
        resource_id=model_id,
        principal_type='user',
        principal_id='*',
        permission='read',
        created_at=0,
    )


def _entry_to_model_model(entry: dict) -> ModelModel:
    # The system prompt is assembled by model_catalogue.system_prompt() and stored under
    # params.system, which is where the completion path reads it from.
    params = dict(entry['params'])
    if entry['system'] is not None:
        params['system'] = entry['system']
    return ModelModel.model_validate(
        {
            'id': entry['id'],
            'user_id': CATALOGUE_USER_ID,
            'base_model_id': entry['base_model_id'],
            'name': entry['name'],
            'params': params,
            'meta': entry['meta'],
            'access_grants': [_catalogue_read_grant(entry['id'])],
            'is_active': entry['is_active'],
            'created_at': entry['created_at'],
            'updated_at': entry['updated_at'],
        }
    )


def catalogue_models() -> list[ModelModel]:
    """The catalogue as ModelModel instances. Built once -- the source cannot change at runtime."""
    global _CATALOGUE_CACHE
    if _CATALOGUE_CACHE is None:
        _CATALOGUE_CACHE = [_entry_to_model_model(entry) for entry in MODEL_CATALOGUE]
    return _CATALOGUE_CACHE


def catalogue_display_names() -> dict[str, str]:
    """id -> display name, including models no longer served.

    Analytics renders historical usage by model id, and chats reference models by id string, so
    a retired model would otherwise show its raw id. The catalogue knows every name it has ever
    defined, which the caller's own model list does not.
    """
    return {entry['id']: entry['name'] for entry in MODEL_CATALOGUE}


class ModelsTable:
    # Sunway: every WRITE method was deleted here (hardening plan Item 9) -- insert, update,
    # toggle, delete, delete_all and sync. ModelsTable reads the code catalogue, so a write
    # would have landed in a table no read path consults. The routes that called them are
    # gone too; see the note in routers/models.py.

    async def get_all_models(self, db: AsyncSession | None = None) -> list[ModelModel]:
        return list(catalogue_models())

    async def get_models(self, db: AsyncSession | None = None) -> list[ModelUserResponse]:
        # Presets only (base_model_id set), matching the previous query's filter.
        return [
            ModelUserResponse.model_validate({**m.model_dump(), 'user': None})
            for m in catalogue_models()
            if m.base_model_id is not None
        ]

    async def get_base_models(self, db: AsyncSession | None = None) -> list[ModelModel]:
        return [m for m in catalogue_models() if m.base_model_id is None]

    async def get_models_by_user_id(
        self, user_id: str, permission: str = 'write', db: AsyncSession | None = None
    ) -> list[ModelUserResponse]:
        # Catalogue models are readable by everyone and writable by no one, so this collapses
        # to a permission check rather than a per-user grant lookup. See the note above
        # ModelsTable: per-group scoping is deliberately not supported.
        if permission != 'read':
            return []
        return await self.get_models(db=db)

    async def search_models(
        self,
        user_id: str,
        filter: dict = {},
        skip: int = 0,
        limit: int = 30,
        db: AsyncSession | None = None,
    ) -> ModelListResponse:
        # Catalogue-backed. The old query filtered by access grant and joined the owning user;
        # neither applies now -- every model is readable by everyone and none has an owner.
        items = [m for m in catalogue_models() if m.base_model_id is not None]

        query_key = (filter or {}).get('query')
        if query_key:
            needle = query_key.lower()
            items = [m for m in items if needle in m.name.lower() or needle in (m.base_model_id or '').lower()]

        total = len(items)
        page = items[skip : skip + limit] if limit else items[skip:]
        return ModelListResponse(
            items=[ModelUserResponse.model_validate({**m.model_dump(), 'user': None}) for m in page],
            total=total,
        )

    async def get_model_meta_by_id(self, id: str, db: AsyncSession | None = None) -> tuple[dict, int | None]:
        """Return (meta, updated_at) for a model, or None if it is not in the catalogue."""
        model = next((m for m in catalogue_models() if m.id == id), None)
        return (model.meta.model_dump(), model.updated_at) if model else None

    async def get_all_tags(
        self,
        user_id: str,
        is_admin: bool = False,
        db: AsyncSession | None = None,
    ) -> set[str]:
        """Unique tag names across catalogue presets.

        No permission filtering: every catalogue model is readable by everyone, so the admin
        and non-admin answers are the same.
        """
        tags_set: set[str] = set()
        for model in catalogue_models():
            if model.base_model_id is None:
                continue
            for tag in getattr(model.meta, 'tags', None) or []:
                name = tag.get('name') if isinstance(tag, dict) else tag
                if isinstance(name, str) and name:
                    tags_set.add(name)
        return tags_set

    async def get_model_by_id(self, id: str, db: AsyncSession | None = None) -> ModelModel | None:
        return next((m for m in catalogue_models() if m.id == id), None)

    async def get_models_by_ids(self, ids: list[str], db: AsyncSession | None = None) -> list[ModelModel]:
        wanted = set(ids)
        return [m for m in catalogue_models() if m.id in wanted]


Models = ModelsTable()  # singleton model registry
