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

export const ALL_ADMIN_SETTINGS_TAB_IDS = ['models'];

// Sunway: 'pipelines' is gone from both lists (hardening plan Item 2). The tab used to be
// hidden here, but the router, the component and the API clients are now deleted outright, so
// there is no longer a tab to hide.
// Sunway: the hide-list is empty because there is nothing left to hide (hardening plan Item 7).
// Every other tab configured settings at runtime, and those endpoints are deleted -- config now
// comes from the chart. Only Models survives, because POST /api/v1/models/import is still the way
// presets are loaded into a tenant until Item 9 makes model definitions code.
export const HIDDEN_ADMIN_SETTINGS_TAB_IDS: string[] = [];

export const VISIBLE_ADMIN_SETTINGS_TAB_IDS = ALL_ADMIN_SETTINGS_TAB_IDS.filter(
	(id) => !HIDDEN_ADMIN_SETTINGS_TAB_IDS.includes(id)
);

// The fallback tab used to be a hard-coded 'general'. Now that 'general' is itself hideable it
// has to be derived, or hiding it would drop the tab button while `selectedTab` still resolved
// to 'general' and the panel would render anyway.
export const DEFAULT_ADMIN_SETTINGS_TAB = VISIBLE_ADMIN_SETTINGS_TAB_IDS[0] ?? 'general';
