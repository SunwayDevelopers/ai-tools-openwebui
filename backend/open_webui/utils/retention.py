import asyncio
import logging
import time

from sqlalchemy import text

from open_webui.internal.db import get_async_db_context
from open_webui.models.chats import Chats
from open_webui.models.files import Files
from open_webui.models.knowledge import Knowledges
from open_webui.retrieval.vector.async_client import ASYNC_VECTOR_DB_CLIENT
from open_webui.storage.provider import Storage

log = logging.getLogger(__name__)


async def purge_file(file, db=None) -> bool:
    """Fully remove a single file everywhere it lives:

      - its membership + embeddings in any Knowledge Base collection
      - its row in the `file` table
      - its bytes in the storage backend (local/S3/GCS/Azure)
      - its own `file-{id}` vector collection

    Shared by the file-delete API route and the retention cascade so both behave
    identically. The CALLER decides *which* files to purge -- e.g. the retention
    cascade never calls this on a file that is still in a KB or another chat.

    Raises on storage/vector failure (the API route translates that to a 400);
    returns False only if the DB row delete itself failed.
    """
    file_id = file.id

    # KB associations + per-KB embeddings (mirrors /knowledge/{id}/file/remove)
    knowledges = await Knowledges.get_knowledges_by_file_id(file_id, db=db)
    for knowledge in knowledges:
        await Knowledges.remove_file_from_knowledge_by_id(knowledge.id, file_id, db=db)
        try:
            await ASYNC_VECTOR_DB_CLIENT.delete(collection_name=knowledge.id, filter={'file_id': file_id})
            if file.hash:
                await ASYNC_VECTOR_DB_CLIENT.delete(collection_name=knowledge.id, filter={'hash': file.hash})
        except Exception as e:
            log.debug(f'KB embedding cleanup for {knowledge.id}: {e}')

    if not await Files.delete_file_by_id(file_id, db=db):
        return False

    await asyncio.to_thread(Storage.delete_file, file.path)
    await ASYNC_VECTOR_DB_CLIENT.delete(collection_name=f'file-{file_id}')
    return True


async def purge_chats_files(chat_ids, db=None) -> int:
    """Purge files referenced ONLY within this set of chats.

    Skips any file that is (a) in a Knowledge Base, or (b) still referenced by a
    chat OUTSIDE this set -- so neither a KB nor a surviving chat is ever broken.
    Used for single deletes (one-element set), bulk/folder deletes, and the
    retention sweep. Call BEFORE deleting the chats (the `chat_file` join rows
    cascade away with the chat). Best-effort: a per-file failure is logged and
    the rest continue. Returns the number of files purged.
    """
    chat_id_set = set(chat_ids)
    if not chat_id_set:
        return 0

    file_ids: set[str] = set()
    for chat_id in chat_id_set:
        for cf in await Chats.get_chat_files_by_chat_id(chat_id, db=db):
            file_ids.add(cf.file_id)

    purged = 0
    for file_id in file_ids:
        if await Knowledges.get_knowledges_by_file_id(file_id, db=db):
            log.debug(f'Retention: keeping file {file_id} (in a knowledge base)')
            continue

        referencing = set(await Chats.get_chat_ids_by_file_id(file_id, db=db))
        if referencing - chat_id_set:
            log.debug(f'Retention: keeping file {file_id} (referenced by a surviving chat)')
            continue

        file = await Files.get_file_by_id(file_id, db=db)
        if not file:
            continue
        try:
            if await purge_file(file, db=db):
                purged += 1
        except Exception as e:
            log.warning(f'Retention: failed to purge file {file_id}: {e}')

    return purged


async def purge_chat_files(chat_id: str, db=None) -> int:
    """Purge files owned exclusively by a single chat. Thin wrapper over
    purge_chats_files so single and bulk deletes share one code path."""
    return await purge_chats_files([chat_id], db=db)


async def run_retention_sweep(retention_days: int, batch_limit: int, db=None) -> int:
    """One retention pass: find chats whose last activity (`updated_at`) is older
    than `retention_days`, purge the files/vectors they exclusively own, then
    delete the chats. Processes at most `batch_limit` chats per call (the
    scheduler calls this once per interval). Returns the number of chats deleted.
    """
    cutoff = int(time.time()) - retention_days * 86400
    chat_ids = await Chats.get_expired_chat_ids(cutoff, limit=batch_limit, db=db)
    if not chat_ids:
        return 0

    # Purge the whole expiring set first so a file shared across several expiring
    # chats is handled correctly, then delete the chats.
    await purge_chats_files(chat_ids, db=db)

    deleted = 0
    for chat_id in chat_ids:
        if await Chats.delete_chat_by_id(chat_id, db=db):
            deleted += 1

    log.info(f'Retention sweep: deleted {deleted}/{len(chat_ids)} chat(s) inactive >{retention_days}d')
    return deleted


# Orphan reaper -- one-time/occasional cleanup of files left behind by chat
# deletions that pre-date the cascade. A file is an orphan ONLY if it is old AND
# referenced NOWHERE: not in chat_file / knowledge_file / channel_file, and its
# id does not appear in any note.data or chat.chat JSON. The JSON scans are
# deliberately conservative (substring match on the id) -- a false positive keeps
# a live file; there are no false negatives. POSTGRES-specific (`::text`, `->>`).
_ORPHAN_FILES_SQL = text(
    """
    SELECT f.id AS id, COALESCE(NULLIF(f.meta->>'size', '')::bigint, 0) AS size
    FROM file f
    WHERE f.created_at < :cutoff
      AND NOT EXISTS (SELECT 1 FROM chat_file cf WHERE cf.file_id = f.id)
      AND NOT EXISTS (SELECT 1 FROM knowledge_file kf WHERE kf.file_id = f.id)
      AND NOT EXISTS (SELECT 1 FROM channel_file chf WHERE chf.file_id = f.id)
      AND NOT EXISTS (SELECT 1 FROM note n WHERE n.data::text LIKE '%' || f.id || '%')
      AND NOT EXISTS (SELECT 1 FROM chat c WHERE c.chat::text LIKE '%' || f.id || '%')
    ORDER BY f.created_at ASC
    LIMIT :limit
    """
)


async def find_orphan_file_ids(older_than_days: int, limit: int, db=None) -> list[dict]:
    """Up to `limit` orphaned files (oldest first): older than `older_than_days`
    and referenced by no chat, knowledge base, channel, note, or chat content.
    Read-only. Returns [{'id', 'size'}]. The note/chat JSON scans are full-table
    per candidate, so run off-peak / batched on large datasets.
    """
    cutoff = int(time.time()) - older_than_days * 86400
    async with get_async_db_context(db) as session:
        result = await session.execute(_ORPHAN_FILES_SQL, {'cutoff': cutoff, 'limit': limit})
        return [{'id': row.id, 'size': int(row.size or 0)} for row in result]


async def reap_orphan_files(older_than_days: int, batch_limit: int, dry_run: bool = True, db=None) -> dict:
    """Find orphaned files and, unless `dry_run`, purge each via purge_file (DB
    row + storage bytes + file-{id} vector collection). DRY-RUN by default --
    review the report before purging. Returns a summary dict.
    """
    candidates = await find_orphan_file_ids(older_than_days, batch_limit, db=db)
    summary = {
        'found': len(candidates),
        'bytes': sum(c['size'] for c in candidates),
        'purged': 0,
        'dry_run': dry_run,
        'sample': [c['id'] for c in candidates[:10]],
    }
    if dry_run or not candidates:
        return summary
    for c in candidates:
        file = await Files.get_file_by_id(c['id'], db=db)
        if not file:
            continue
        try:
            if await purge_file(file, db=db):
                summary['purged'] += 1
        except Exception as e:
            log.warning(f"Orphan reap: failed to purge file {c['id']}: {e}")
    log.info(f"Orphan reap: purged {summary['purged']}/{summary['found']} orphaned files ({summary['bytes']} bytes)")
    return summary
