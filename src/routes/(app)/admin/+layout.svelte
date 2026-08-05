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

	// Sunway: Evaluations and Functions are hidden for EVERYONE incl. super admins (see
	// CLAUDE.md → "Deferred / hidden features"). This blocks direct-URL access too, so there is
	// no back-door into the hidden screens.
	//
	// Reactive, not onMount-only, for the same reason as the Workspace layout: onMount fires
	// once per layout mount, so a client-side navigation from /admin/users to /admin/functions
	// would reuse this already-mounted layout and slip straight past an onMount check. There are
	// no in-app links left to either screen, so today this is belt-and-braces — but it is the
	// identical defect that made clicking "Workspace" render the hidden Models page.
	//
	// NOTE: hiding the Functions UI does NOT disable Filter functions — any already-installed
	// inlet/outlet filter keeps running in utils/middleware.py. This only removes the
	// install/edit surface. Reverse by removing this block + the two nav gates below.
	const HIDDEN_ADMIN_PATHS = ['/admin/evaluations', '/admin/functions'];

	$: if (browser && HIDDEN_ADMIN_PATHS.some((path) => $page.url.pathname.includes(path))) {
		loaded = false;
		goto('/admin');
	}

	onMount(async () => {
		if ($user?.role !== 'admin') {
			await goto('/');
			return;
		}

		if (HIDDEN_ADMIN_PATHS.some((path) => $page.url.pathname.includes(path))) {
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

						<!-- Sunway: Functions hidden. NOTE this reverses the earlier "deliberately still
						     admin-visible" call recorded in CLAUDE.md — Filter functions carry the
						     inlet/outlet hooks the guardrail work depends on. Hiding the UI does NOT
						     stop installed filters from running (utils/middleware.py is untouched); it
						     only removes the install/edit surface, so the guardrail work will need this
						     un-hidden when it starts. Original gate: always visible to admins -->
						{#if false}
							<a
								draggable="false"
								class="min-w-fit p-1.5 {$page.url.pathname.includes('/admin/functions')
									? ''
									: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition select-none"
								href="/admin/functions">{$i18n.t('Functions')}</a
							>
						{/if}

						<a
							draggable="false"
							class="min-w-fit p-1.5 {$page.url.pathname.includes('/admin/settings')
								? ''
								: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition select-none"
							href="/admin/settings">{$i18n.t('Settings')}</a
						>
					</div>
				</div>
			</div>
		</nav>

		<div class="  pb-1 flex-1 max-h-full overflow-y-auto">
			<slot />
		</div>
	</div>
{/if}
