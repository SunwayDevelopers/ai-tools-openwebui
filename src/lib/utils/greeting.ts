// Sunway: time-aware new-chat greeting for the placeholder heading.
//
// Two design constraints drive this file:
//   1. The name is the risk, not the copy. `user.name` is a display name that, once SSO /
//      Entra provisioning lands, comes from the company directory — often a full legal name,
//      frequently uppercase, sometimes with Malay honorifics ("bin"/"binti") or a different
//      name order. Getting someone's name wrong on *every* new chat is worse than not naming
//      them, so anything that looks unsafe to shorten falls back to a name-less greeting.
//   2. The pick must be frozen at mount by the caller (a `const`), never recomputed reactively,
//      or the heading re-rolls and flickers while the user types.
//
// Translation stays in the caller (a .svelte file), because the i18n parser only scans
// .js/.svelte for *static* `$i18n.t('literal')` calls and strips anything else — a key built
// here would never be extracted. So this module is pure logic (name + time of day) and the
// component maps the result onto static `t()` literals.

export type TimeOfDay = 'morning' | 'afternoon' | 'evening';

export const getTimeOfDay = (date: Date = new Date()): TimeOfDay => {
	const h = date.getHours();
	if (h < 12) return 'morning';
	if (h < 18) return 'afternoon';
	return 'evening';
};

// Leading tokens that must never be shown as a first name. Deliberately limited to
// *unambiguous* patronymic connectors, professional titles, and religious titles — tokens
// that are essentially never someone's given name.
//
// We intentionally do NOT strip Malay award titles (Dato', Datin, Datuk, Tan Sri, ...): "Tan"
// is overwhelmingly a Chinese-Malaysian *surname*, so stripping it would greet the wrong name
// far more often than it would strip a real title. Better to occasionally greet a rare award
// title verbatim than to routinely mis-name a Tan.
const HONORIFICS = new Set([
	'bin',
	'binti',
	'bt',
	'bte',
	'dr',
	'prof',
	'mr',
	'mrs',
	'ms',
	'mdm',
	'madam',
	'sir',
	'haji',
	'hajjah'
]);

// Title-case a single ALL-CAPS or lower token ("KHAIRUL" -> "Khairul"), but leave a token that
// already has internal capitals alone ("McArthur", "O'Brien") so we don't mangle it.
const titleCaseToken = (token: string): string => {
	const stripped = token.replace(/[.,]/g, '');
	const isUniformCase = stripped === stripped.toUpperCase() || stripped === stripped.toLowerCase();
	if (!isUniformCase) return token;
	return token.charAt(0).toUpperCase() + token.slice(1).toLowerCase();
};

/**
 * Derive a safe first name from a display name, or null when it can't be done confidently.
 * Returning null is the signal to use the name-less greeting variant.
 */
export const deriveFirstName = (rawName?: string | null): string | null => {
	if (!rawName) return null;

	const trimmed = rawName.trim();
	if (!trimmed) return null;

	// Looks like an email local-part or handle rather than a human name — don't guess.
	if (/[@_]/.test(trimmed) || trimmed.includes('://')) return null;

	// Split on whitespace; drop leading honorifics so "Dr Tan Wei" -> "Tan", "Bin Abdullah" -> null-ish.
	const tokens = trimmed.split(/\s+/).filter(Boolean);
	if (tokens.length === 0) return null;

	let idx = 0;
	while (idx < tokens.length && HONORIFICS.has(tokens[idx].replace(/[.,]/g, '').toLowerCase())) {
		idx++;
	}
	// The whole thing was honorifics (or nothing usable is left).
	if (idx >= tokens.length) return null;

	const candidate = tokens[idx];

	// Must be a plausible name token: letters (incl. accents/apostrophes/hyphens), 2+ chars,
	// and not purely digits/symbols. This rejects "x", "123", "-", etc.
	if (!/^[\p{L}][\p{L}'’-]+$/u.test(candidate)) return null;

	return titleCaseToken(candidate);
};

// Greeting variants. `timeOfDay` resolves to the morning/afternoon/evening line; the rest are
// time-neutral openers. Kept deliberately warm-but-plain — no slang, no exclamation marks, and
// nothing that reads as chummy when a 10K-employee directory sees it every new chat.
export type GreetingVariant =
	| 'timeOfDay'
	| 'welcomeBack'
	| 'readyWhenYouAre'
	| 'whatCanIHelpWith'
	| 'whatAreWeWorkingOn'
	| 'whereShouldWeStart'
	| 'whatsOnYourMind';

const NEUTRAL_VARIANTS: GreetingVariant[] = [
	'welcomeBack',
	'readyWhenYouAre',
	'whatCanIHelpWith',
	'whatAreWeWorkingOn',
	'whereShouldWeStart',
	'whatsOnYourMind'
];

// Half the time we still show the time-of-day line — it's the variant that carries the most
// signal (it proves the app knows *when* you are), so it shouldn't get diluted to 1/7th by the
// neutral pool. The other half spreads evenly across the neutral openers.
const TIME_OF_DAY_SHARE = 0.5;

/**
 * Pick which greeting to show. Call once and freeze the result (see the note at the top of this
 * file) — re-rolling on a reactive statement makes the heading flicker as the user types.
 *
 * `previous` excludes the last variant shown, so the same line never appears twice in a row.
 * Independent uniform sampling *feels* broken to users — back-to-back repeats are common at
 * this pool size, and people read a repeat as "it isn't actually random" rather than as chance.
 * Excluding the previous pick costs nothing and removes the only artifact anyone notices.
 *
 * `random` is injectable so the choice is testable.
 */
export const pickGreetingVariant = (
	random: () => number = Math.random,
	previous?: GreetingVariant | null
): GreetingVariant => {
	// Always drawn, even when the time-of-day branch is excluded, so the number of random()
	// calls doesn't depend on `previous` — that keeps stubbed sequences predictable in tests.
	const roll = random();
	if (previous !== 'timeOfDay' && roll < TIME_OF_DAY_SHARE) return 'timeOfDay';

	const pool = NEUTRAL_VARIANTS.filter((variant) => variant !== previous);

	// Clamp: Math.random() is [0,1) but an injected stub may return exactly 1.
	const idx = Math.min(Math.floor(random() * pool.length), pool.length - 1);
	return pool[idx];
};

const LAST_GREETING_KEY = 'schat:last-greeting-variant';

/**
 * Browser-side wrapper around `pickGreetingVariant` that remembers the last pick for the tab,
 * so "no immediate repeat" holds across new chats and not just within one mount. sessionStorage
 * (not localStorage) on purpose: this is throwaway presentation state, and it should reset when
 * the user starts a fresh session rather than persist on a shared/kiosk machine.
 */
export const pickNextGreetingVariant = (): GreetingVariant => {
	let previous: GreetingVariant | null = null;

	try {
		previous = sessionStorage.getItem(LAST_GREETING_KEY) as GreetingVariant | null;
	} catch {
		// Private mode / storage disabled — fall back to an unconstrained pick.
	}

	const variant = pickGreetingVariant(Math.random, previous);

	try {
		sessionStorage.setItem(LAST_GREETING_KEY, variant);
	} catch {
		// Non-fatal: we just lose repeat-avoidance for this tab.
	}

	return variant;
};
