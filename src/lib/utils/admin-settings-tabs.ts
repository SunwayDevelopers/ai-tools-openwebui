// Sunway: which Admin Settings tabs are hidden, and what the fallback tab is.
//
// Lives in its own module because two places need it: the tab list / panel switch in
// `components/admin/Settings.svelte`, and the entry redirect in
// `routes/(app)/admin/settings/+page.svelte` (which used to hard-code '/general').
// Keeping one source of truth means hiding a tab can never leave the redirect pointing
// at a tab that no longer renders.
//
// Every tab's definition and panel markup is left fully intact — ids here are filtered
// out of the tab list and dropped from the valid-path list, so a direct URL such as
// /admin/settings/audio falls back to the first visible tab instead of rendering.
// Reverse by removing ids from HIDDEN_ADMIN_SETTINGS_TAB_IDS.
// See CLAUDE.md → "Deferred / hidden features" for the per-tab rationale.

export const ALL_ADMIN_SETTINGS_TAB_IDS = [
	'general',
	'connections',
	'models',
	'evaluations',
	'integrations',
	'documents',
	'web',
	'code-execution',
	'interface',
	'audio',
	'images',
	'pipelines',
	'db'
];

export const HIDDEN_ADMIN_SETTINGS_TAB_IDS = [
	// version/update check (ENABLE_VERSION_UPDATE_CHECK=false) + upstream Open WebUI help and
	// licence links + signup / default-role / LDAP — all now owned by the IAM + multi-tenancy
	// layer. Note what this DOES take away: enterprise-licence activation, and the JWT expiry /
	// API-key endpoint restrictions. See CLAUDE.md.
	'general',
	// no evaluation programme; ratings off (ENABLE_MESSAGE_RATING=false) and arena models
	// disabled, so the feedback/arena config is dead config
	'evaluations',
	// task-model selection + title/tag/query-generation prompts. Hidden on the same call as the
	// user-facing Settings → Interface tab
	'interface',
	// Code Interpreter deferred. Re-hidden 2026-08-05 AFTER the toggle was flipped off in this
	// tab: ENABLE_CODE_INTERPRETER is PersistentConfig, so the stored DB value now wins and this
	// tab is the only UI that can change it. If it ever needs flipping again, remove this id.
	'code-execution',
	// Voice out of scope (ENABLE_VOICE=false); STT/TTS config is unreachable
	'audio',
	// arbitrary-code plugin surface, same class as Workspace → Tools
	'pipelines',
	// DB export/import/backup; an ops job, not a UI job (ISO 27001: backups are handled at the
	// cluster/Helm layer, not by a browser download button)
	'db'
];

export const VISIBLE_ADMIN_SETTINGS_TAB_IDS = ALL_ADMIN_SETTINGS_TAB_IDS.filter(
	(id) => !HIDDEN_ADMIN_SETTINGS_TAB_IDS.includes(id)
);

// The fallback tab used to be a hard-coded 'general'. Now that 'general' is itself hideable it
// has to be derived, or hiding it would drop the tab button while `selectedTab` still resolved
// to 'general' and the panel would render anyway.
export const DEFAULT_ADMIN_SETTINGS_TAB = VISIBLE_ADMIN_SETTINGS_TAB_IDS[0] ?? 'general';
