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
	// FUNCTIONS DELETED 2026-08-14 (hardening plan Item 2). The router, pages and API client
	// are gone, so there is no longer a page to gate; ENABLE_ADMIN_FUNCTIONS_UI is retired.
	// The guardrail filter it used to host is now a code module under
	// backend/open_webui/filters/, which cannot be installed, re-valved or toggled over HTTP.
	//
	// SETTINGS DELETED 2026-08-17 (hardening plan Items 7 and 9). Configuration comes from the
	// chart and models from backend/open_webui/model_catalogue.py, so the page had nothing left
	// to edit; ENABLE_ADMIN_SETTINGS_UI is retired with it. There is now no runtime admin
	// surface that writes process-global config -- which was the whole reason it was gated.
	//
	// FAIL CLOSED (changed 2026-08-12). This used to read `=== false`, i.e. "hide only when
	// the backend explicitly says false", so an ABSENT flag meant visible. That is precisely
	// how the August 2026 VAPT tester reached Functions and Settings by direct URL: /api/config
	// dropped its whole feature block for him (he had no row in the DATABASE_URL tenant — see
	// main.py:_resolve_config_user_multi_tenant), the flags arrived undefined rather than false,
	// and every gate here opened.
	//
	// The original concern behind `=== false` was real and is preserved: $config is null on the
	// first render, and treating "not loaded yet" as "hidden" would bounce an admin off a page
	// they are allowed to see. So the two cases are now distinguished explicitly —
	//   config not loaded yet  → do NOT redirect (wait for it)
	//   config loaded, flag not exactly true → hide, including direct-URL access
	$: configLoaded = $config !== null && $config !== undefined;

	// Nothing left to hide: every flag-gated admin page has been deleted rather than gated.
	// Kept as an empty list, and the guard below with it, so re-introducing a gated page is a
	// one-line change and cannot reintroduce the fail-open bug described above.
	$: hiddenAdminPaths = [];

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
		<nav class="   px-2.5 pt-1.5 pb-2 backdrop-blur-xl drag-region select-none">
			<div class=" flex items-center gap-1">
				{#if $mobile}
					<div class="{$showSidebar ? 'md:hidden' : ''} flex flex-none items-center self-end">
						<Tooltip
							content={$showSidebar ? $i18n.t('Close Sidebar') : $i18n.t('Open Sidebar')}
							interactive={true}
						>
							<button
								id="sidebar-toggle-button"
								class=" cursor-pointer flex rounded-lg brand-nav-item transition cursor-"
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
							class="min-w-fit select-none {$page.url.pathname.includes('/admin/users')
								? 'brand-pill-solid'
								: 'brand-pill-outline'}"
							href="/admin">{$i18n.t('Users')}</a
						>

						{#if $config?.features.enable_admin_analytics ?? true}
							<a
								draggable="false"
								class="min-w-fit select-none {$page.url.pathname.includes('/admin/analytics')
									? 'brand-pill-solid'
									: 'brand-pill-outline'}"
								href="/admin/analytics">{$i18n.t('Analytics')}</a
							>
						{/if}

						<!-- Sunway: the Evaluations nav entry was deleted here (hardening plan Item 6).
						     It was already hidden; the router, pages and API client are now gone too. -->

						<!-- Sunway: the Functions nav entry was deleted here (hardening plan Item 2,
						     frontend half). The Functions router, its pages and its API client are all
						     gone -- a "Function" was Python source in a database row, exec()'d on the
						     server. The guardrail filter that used to live there is now a code module
						     (backend/open_webui/filters/), so nothing needs this install surface.
						     ENABLE_ADMIN_FUNCTIONS_UI is retired with it. -->

						<!-- Sunway: the Settings nav entry was deleted here (Items 7 and 9). See the
						     note at the top of this file. -->
					</div>
				</div>
			</div>
		</nav>

		<div class="  pb-1 flex-1 max-h-full overflow-y-auto">
			<slot />
		</div>
	</div>
{/if}
