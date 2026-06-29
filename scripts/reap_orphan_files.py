"""One-time / occasional orphan-file reaper for schat.ai retention.

Cleans up files left behind by chat deletions that pre-date the purge cascade.
A file is reaped ONLY if it is old AND referenced nowhere -- no chat, knowledge
base, channel, note, or chat content (see utils.retention.find_orphan_file_ids).

DRY-RUN by default: reports what WOULD be deleted. Pass --purge to delete.
Run inside the app environment (env vars set), e.g. in the backend container:

  python scripts/reap_orphan_files.py --days 30 --batch 500            # dry-run
  python scripts/reap_orphan_files.py --days 30 --batch 500 --purge    # delete

Recommended: dry-run first and review the count / sample; then --purge in
batches (re-run until 'found' is 0). Run off-peak -- the note/chat JSON scans
are full-table per candidate.
"""
import argparse
import asyncio

from open_webui.utils.retention import reap_orphan_files


async def main() -> None:
    parser = argparse.ArgumentParser(description='Reap orphaned files (dry-run by default).')
    parser.add_argument('--days', type=int, default=30, help='only consider files older than N days (default: 30)')
    parser.add_argument('--batch', type=int, default=500, help='max files processed per run (default: 500)')
    parser.add_argument('--purge', action='store_true', help='actually delete (default: dry-run, report only)')
    args = parser.parse_args()

    summary = await reap_orphan_files(args.days, args.batch, dry_run=not args.purge)

    mode = 'PURGE' if args.purge else 'DRY-RUN (no deletion)'
    mb = summary['bytes'] / (1024 * 1024)
    print(f"\n=== ORPHAN-FILE REAP [{mode}] ===")
    print(f"  older than : {args.days} days     batch limit : {args.batch}")
    print(f"  orphans found : {summary['found']}   (~{mb:.1f} MB)")
    if args.purge:
        print(f"  files purged  : {summary['purged']}")
    if summary['sample']:
        print(f"  sample ids    : {', '.join(summary['sample'])}")
    if not args.purge and summary['found']:
        print("\n  Review the above, then re-run with --purge to delete (batched).")


if __name__ == '__main__':
    asyncio.run(main())
