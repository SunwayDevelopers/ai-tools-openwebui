// Sunway: shared maths for the chat-retention UI.
//
// The backend sweep (backend/open_webui/utils/retention.py) expires a chat when it has been
// inactive for CHAT_RETENTION_DAYS, measured from `updated_at` — NOT `created_at`. Any UI that
// warns about expiry has to use the same field or it will lie to the user: an old chat that was
// replied to yesterday is not close to expiring, and the sidebar's "time ago" label (which is
// created_at based) would suggest otherwise.
//
// Lives here rather than inside RetentionNotice.svelte because two components need the same
// answer: the notice renders the badge, and ChatItem has to know whether a badge *will* render
// before deciding whether to show the time-ago label in that slot instead.

/** Seconds in a day. */
const DAY = 86400;

/**
 * Whole days until a chat is swept, rounded up, or null when retention is off or the timestamp
 * is missing. Can go negative for a chat already past its expiry that the sweep hasn't collected
 * yet (the sweep runs on the background scheduler, not continuously) — callers clamp for display.
 *
 * @param updatedAt    epoch SECONDS (the API's `updated_at`), not milliseconds
 * @param retentionDays 0 / negative disables retention
 * @param now          epoch milliseconds, injectable for tests
 */
export const getDaysUntilExpiry = (
	updatedAt?: number | null,
	retentionDays?: number | null,
	now: number = Date.now()
): number | null => {
	if (!updatedAt || !retentionDays || retentionDays <= 0) return null;

	return Math.ceil((updatedAt + retentionDays * DAY - now / 1000) / DAY);
};

/**
 * Whether a chat is close enough to expiry to warrant the inline warning badge.
 * Past-due chats (negative days) still count — they're the most urgent case.
 */
export const isNearExpiry = (
	updatedAt?: number | null,
	retentionDays?: number | null,
	thresholdDays = 7,
	now: number = Date.now()
): boolean => {
	const daysLeft = getDaysUntilExpiry(updatedAt, retentionDays, now);
	return daysLeft !== null && daysLeft <= thresholdDays;
};
