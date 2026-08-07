<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { browser } from '$app/environment';

	import { WEBUI_NAME, config, mobile, showSidebar, user } from '$lib/stores';
	import { page } from '$app/stores';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

	import Sidebar from '$lib/components/icons/Sidebar.svelte';

	const i18n = getContext('i18n');

	let loaded = false;

	// Sunway: Evaluations is hidden for EVERYONE incl. super admins (see CLAUDE.md →
	// "Deferred / hidden features"). This blocks direct-URL access too, so there is no
	// back-door into the hidden screen.
	//
	// Reactive, not onMount-only, for the same reason as the Workspace layout: onMount fires
	// once per layout mount, so a client-side navigation from /admin/users would reuse this
	// already-mounted layout and slip straight past an onMount check. That is the identical
	// defect that made clicking "Workspace" render the hidden Models page.
	//
	// FUNCTIONS UN-HIDDEN 2026-08-05 — it was hidden earlier the same day, then restored
	// because Filter functions carry the inlet/outlet hooks the guardrail work attaches to,
	// and the UI is the only place to install, edit, order or toggle a filter. Hiding it never
	// disabled anything (utils/middleware.py still ran installed filters); it only blocked the
	// install surface, which would have blocked the guardrail work itself.
	//
	// Functions and Settings are now flag-driven rather than hard-coded, so the guardrail can
	// be tuned by flipping ENABLE_ADMIN_FUNCTIONS_UI without editing source. Both are PLAIN
	// env (see env.py for why Settings especially must never be PersistentConfig).
	//
	// `=== false` deliberately, not falsy: $config is null on the first render, and treating
	// "not loaded yet" as "hidden" would bounce an admin off a page they are allowed to see.
	// Absent flag → visible, which is also what an older backend returns.
	$: hiddenAdminPaths = [
		'/admin/evaluations',
		...($config?.features?.enable_admin_functions_ui === false ? ['/admin/functions'] : []),
		...($config?.features?.enable_admin_settings_ui === false ? ['/admin/settings'] : [])
	];

	$: if (browser && hiddenAdminPaths.some((path) => $page.url.pathname.includes(path))) {
		loaded = false;
		goto('/admin');
	}

	onMount(async () => {
		if ($user?.role !== 'admin') {
			await goto('/');
			return;
		}

		if (hiddenAdminPaths.some((path) => $page.url.pathname.includes(path))) {
			return;
		}

		loaded = true;
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Admin Panel')} • {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<div
		class=" flex flex-col h-screen max-h-[100dvh] flex-1 transition-width duration-200 ease-in-out {$showSidebar
			? 'md:max-w-[calc(100%-var(--sidebar-width))]'
			: ' md:max-w-[calc(100%-49px)]'}  w-full max-w-full"
	>
		<nav class="   px-2.5 pt-1.5 backdrop-blur-xl drag-region select-none">
			<div class=" flex items-center gap-1">
				{#if $mobile}
					<div class="{$showSidebar ? 'md:hidden' : ''} flex flex-none items-center self-end">
						<Tooltip
							content={$showSidebar ? $i18n.t('Close Sidebar') : $i18n.t('Open Sidebar')}
							interactive={true}
						>
							<button
								id="sidebar-toggle-button"
								class=" cursor-pointer flex rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition cursor-"
								on:click={() => {
									showSidebar.set(!$showSidebar);
								}}
							>
								<div class=" self-center p-1.5">
									<Sidebar />
								</div>
							</button>
						</Tooltip>
					</div>
				{/if}

				<div class=" flex w-full">
					<div
						class="flex gap-1 scrollbar-none overflow-x-auto w-fit text-center text-sm font-medium rounded-full bg-transparent pt-1"
					>
						<a
							draggable="false"
							class="min-w-fit p-1.5 {$page.url.pathname.includes('/admin/users')
								? ''
								: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition select-none"
							href="/admin">{$i18n.t('Users')}</a
						>

						{#if $config?.features.enable_admin_analytics ?? true}
							<a
								draggable="false"
								class="min-w-fit p-1.5 {$page.url.pathname.includes('/admin/analytics')
									? ''
									: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition select-none"
								href="/admin/analytics">{$i18n.t('Analytics')}</a
							>
						{/if}

						<!-- Sunway: Evaluations hidden — the evaluation programme does not exist and
						     Good/Bad response ratings are off (ENABLE_MESSAGE_RATING=false), so the
						     leaderboard/feedback screens are permanently dataless. Arena models are
						     disabled in Admin Settings too. Original gate: always visible to admins -->
						{#if false}
							<a
								draggable="false"
								class="min-w-fit p-1.5 {$page.url.pathname.includes('/admin/evaluations')
									? ''
									: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition select-none"
								href="/admin/evaluations">{$i18n.t('Evaluations')}</a
							>
						{/if}

						<!-- Sunway: Filter functions are the inlet/outlet attachment point for the
						     prompt/content guardrails, and this UI is the only way to install, edit,
						     order or toggle one — so hiding it blocks guardrail work, not the
						     guardrails themselves (utils/middleware.py keeps running installed
						     filters either way). Gated on ENABLE_ADMIN_FUNCTIONS_UI so it can be
						     reopened for tuning without a code change.
						     Note `admin` does NOT distinguish super admin from BU admin under
						     multi-tenancy, so when visible this is reachable by any tenant admin. -->
						{#if $config?.features?.enable_admin_functions_ui ?? true}
							<a
								draggable="false"
								class="min-w-fit p-1.5 {$page.url.pathname.includes('/admin/functions')
									? ''
									: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition select-none"
								href="/admin/functions">{$i18n.t('Functions')}</a
							>
						{/if}

						<!-- Sunway: Admin Settings writes PROCESS-GLOBAL config — no tenant component,
						     no TTL — so a single BU admin's change propagates to every pod for every
						     tenant. Gated on ENABLE_ADMIN_SETTINGS_UI (plain env; it must never be
						     PersistentConfig, since this is the only screen that could turn it back
						     on). Individual tabs stay filtered by HIDDEN_ADMIN_SETTINGS_TAB_IDS. -->
						{#if $config?.features?.enable_admin_settings_ui ?? true}
							<a
								draggable="false"
								class="min-w-fit p-1.5 {$page.url.pathname.includes('/admin/settings')
									? ''
									: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition select-none"
								href="/admin/settings">{$i18n.t('Settings')}</a
							>
						{/if}
					</div>
				</div>
			</div>
		</nav>

		<div class="  pb-1 flex-1 max-h-full overflow-y-auto">
			<slot />
		</div>
	</div>
{/if}
