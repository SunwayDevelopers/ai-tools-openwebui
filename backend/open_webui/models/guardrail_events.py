import logging
import time
from typing import Optional
from uuid import uuid4

from open_webui.internal.db import Base, get_async_db_context
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, BigInteger, Column, Index, Text, func, select

log = logging.getLogger(__name__)


####################
# GuardrailEvent DB Schema
####################


class GuardrailEvent(Base):
    __tablename__ = 'guardrail_event'

    id = Column(Text, primary_key=True)
    created_at = Column(BigInteger, nullable=False)

    user_id = Column(Text, nullable=True)
    chat_id = Column(Text, nullable=True)

    # 'injection_block' | 'injection_heuristic' | 'pii_redacted' |
    # 'output_credential_redacted' | 'citation_missing'
    event_type = Column(Text, nullable=False)
    # 'message' | 'system_prompt' | 'output'
    source = Column(Text, nullable=True)
    # 'blocked' | 'warned' | 'redacted' | 'logged'
    action = Column(Text, nullable=False)

    # Matched pattern/label names only (e.g. ["NRIC", "EMAIL"]) — never the
    # scanned text. Keeping the scanned content out of this table is what
    # keeps it safe to let admins browse without re-creating the exposure
    # the guardrail exists to prevent.
    patterns = Column(JSON, nullable=True)
    detail = Column(Text, nullable=True)

    __table_args__ = (
        Index('ix_guardrail_event_created_at', 'created_at'),
        Index('ix_guardrail_event_user_id', 'user_id'),
        Index('ix_guardrail_event_event_type', 'event_type'),
    )


####################
# Pydantic Models
####################


class GuardrailEventModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: int

    user_id: Optional[str] = None
    chat_id: Optional[str] = None

    event_type: str
    source: Optional[str] = None
    action: str

    patterns: Optional[list] = None
    detail: Optional[str] = None


class GuardrailEventListResponse(BaseModel):
    items: list[GuardrailEventModel]
    total: int


####################
# GuardrailEventTable
####################


class GuardrailEventTable:
    async def insert(
        self,
        event_type: str,
        action: str,
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        source: Optional[str] = None,
        patterns: Optional[list] = None,
        detail: Optional[str] = None,
    ) -> Optional[GuardrailEventModel]:
        """Fire-and-forget audit write.

        Called from filters/guardrails.py, which is written to never let an
        internal defect take chat down (see its FAILURE POLICY note). A DB
        hiccup here must follow the same rule — it degrades the audit trail,
        not the request — so every caller wraps this in try/except rather
        than this method swallowing errors itself.
        """
        async with get_async_db_context() as db:
            row = GuardrailEvent(
                id=str(uuid4()),
                created_at=int(time.time_ns()),
                user_id=user_id,
                chat_id=chat_id,
                event_type=event_type,
                source=source,
                action=action,
                patterns=patterns,
                detail=detail,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return GuardrailEventModel.model_validate(row)

    async def search(
        self,
        user_id: Optional[str] = None,
        event_type: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
        db=None,
    ) -> GuardrailEventListResponse:
        async with get_async_db_context(db) as db:
            stmt = select(GuardrailEvent)
            if user_id:
                stmt = stmt.filter_by(user_id=user_id)
            if event_type:
                stmt = stmt.filter_by(event_type=event_type)

            count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
            total = count_result.scalar()

            stmt = stmt.order_by(GuardrailEvent.created_at.desc()).offset(skip).limit(limit)
            result = await db.execute(stmt)
            rows = result.scalars().all()
            return GuardrailEventListResponse(
                items=[GuardrailEventModel.model_validate(r) for r in rows],
                total=total,
            )


GuardrailEvents = GuardrailEventTable()
