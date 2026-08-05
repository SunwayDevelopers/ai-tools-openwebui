// Sunway: which Workspace sections are hidden, and where /workspace should land.
//
// Shared by `routes/(app)/workspace/+layout.svelte` (nav + route guard) and
// `routes/(app)/workspace/+page.svelte` (the /workspace entry redirect), for the same
// reason as lib/utils/admin-settings-tabs.ts: the entry redirect used to hard-code
// '/workspace/models', so hiding Models left it redirecting into a hidden section.
//
// Section components and routes are left fully intact — only navigation is gated.
// See CLAUDE.md → "Deferred / hidden features" for the per-section rationale.

export const HIDDEN_WORKSPACE_SECTIONS = [
	// deferred (no custom presets)
	'models',
	// deferred (arbitrary-code risk)
	'tools',
	// deferred — same arbitrary-code class as Tools; schat-ba-docs governance/decisions.md:312
	'skills',
	// hidden 2026-08-05, reversing AUDIT-020: intended BU-admin/user hidden + super-admin
	// visible, but no super-admin tier is expressible yet (both tiers arrive as role === 'admin')
	'prompts'
];

// Order matters: the first visible section is where /workspace lands.
export const ALL_WORKSPACE_SECTIONS = ['models', 'knowledge', 'prompts', 'tools', 'skills'];

export const VISIBLE_WORKSPACE_SECTIONS = ALL_WORKSPACE_SECTIONS.filter(
	(section) => !HIDDEN_WORKSPACE_SECTIONS.includes(section)
);

export const DEFAULT_WORKSPACE_SECTION = VISIBLE_WORKSPACE_SECTIONS[0] ?? null;

export const isHiddenWorkspacePath = (pathname: string): boolean =>
	HIDDEN_WORKSPACE_SECTIONS.some((section) => pathname.includes(`/workspace/${section}`));
