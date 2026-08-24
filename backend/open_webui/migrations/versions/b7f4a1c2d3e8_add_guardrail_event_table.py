"""add guardrail_event table

Revision ID: b7f4a1c2d3e8
Revises: 461111b60977
Create Date: 2026-08-24

Sunway: DB-backed audit trail for filters/guardrails.py security signals
(injection block/heuristic, input PII redaction, output credential
redaction, citation advisory). These previously existed only as
log.warning()/log.info() lines in the backend process log, which the
team's security review flagged as insufficient — an operator log is not
durable, queryable, or exportable evidence for a PDPA/ISO 27001 event
trail. This table adds persistence; the log lines stay as-is for
real-time ops visibility, since they cost nothing extra to keep.
"""

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b7f4a1c2d3e8'
down_revision: Union[str, None] = '461111b60977'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'guardrail_event' not in inspector.get_table_names():
        op.create_table(
            'guardrail_event',
            sa.Column('id', sa.Text(), primary_key=True),
            sa.Column('created_at', sa.BigInteger(), nullable=False),
            sa.Column('user_id', sa.Text(), nullable=True),
            sa.Column('chat_id', sa.Text(), nullable=True),
            # 'injection_block' | 'injection_heuristic' | 'pii_redacted' |
            # 'output_credential_redacted' | 'citation_missing'
            sa.Column('event_type', sa.Text(), nullable=False),
            # 'message' | 'system_prompt' | 'output'
            sa.Column('source', sa.Text(), nullable=True),
            # 'blocked' | 'warned' | 'redacted' | 'logged'
            sa.Column('action', sa.Text(), nullable=False),
            # matched pattern/label names only (e.g. ["NRIC", "EMAIL"]) —
            # never the scanned text itself, so this table never becomes a
            # second place PII can leak.
            sa.Column('patterns', sa.JSON(), nullable=True),
            sa.Column('detail', sa.Text(), nullable=True),
        )

    inspector.clear_cache()
    if 'guardrail_event' in inspector.get_table_names():
        existing = {idx['name'] for idx in inspector.get_indexes('guardrail_event')}
        if 'ix_guardrail_event_created_at' not in existing:
            op.create_index('ix_guardrail_event_created_at', 'guardrail_event', ['created_at'])
        if 'ix_guardrail_event_user_id' not in existing:
            op.create_index('ix_guardrail_event_user_id', 'guardrail_event', ['user_id'])
        if 'ix_guardrail_event_event_type' not in existing:
            op.create_index('ix_guardrail_event_event_type', 'guardrail_event', ['event_type'])


def downgrade():
    op.drop_index('ix_guardrail_event_event_type', table_name='guardrail_event')
    op.drop_index('ix_guardrail_event_user_id', table_name='guardrail_event')
    op.drop_index('ix_guardrail_event_created_at', table_name='guardrail_event')
    op.drop_table('guardrail_event')
