<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import {
		WEBUI_NAME,
		showSidebar,
		functions,
		user,
		mobile,
		models,
		knowledge,
		tools
	} from '$lib/stores';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Sidebar from '$lib/components/icons/Sidebar.svelte';

	import { browser } from '$app/environment';
	import { isHiddenWorkspacePath } from '$lib/utils/workspace-sections';

	const i18n = getContext('i18n');

	let loaded = false;

	// Sunway: Models, Tools, Skills and Prompts are deferred and hidden for EVERYONE incl.
	// admins — see lib/utils/workspace-sections.ts for which and why, and CLAUDE.md →
	// "Deferred / hidden features" for the full record. This blocks direct-URL access so
	// there is no admin back-door into a hidden screen.
	//
	// This guard must be REACTIVE, not onMount-only. onMount fires once per layout mount, and
	// navigating from /workspace to /workspace/models client-side REUSES this already-mounted
	// layout — so the old onMount-only guard never ran and the hidden section rendered anyway.
	// That is exactly how clicking "Workspace" ended up showing Models once Models was hidden.
	// Keying off $page.url.pathname catches every navigation, direct-URL and client-side alike.
	// Clearing `loaded` stops the hidden section painting in the frame before goto() resolves.
	$: if (browser && isHiddenWorkspacePath($page.url.pathname)) {
		loaded = false;
		goto('/');
	}

	onMount(async () => {
		// Sunway: the hidden-section check that used to live here is now the REACTIVE guard
		// above — see the comment there for why onMount was not enough. Rationale for which
		// sections are hidden lives in lib/utils/workspace-sections.ts and CLAUDE.md.
		if (isHiddenWorkspacePath($page.url.pathname)) {
			return;
		}

		if ($user?.role !== 'admin') {
			if ($page.url.pathname.includes('/models') && !$user?.permissions?.workspace?.models) {
				goto('/');
			} else if (
				$page.url.pathname.includes('/knowledge') &&
				!$user?.permissions?.workspace?.knowledge
			) {
				goto('/');
			} else if (
				$page.url.pathname.includes('/prompts') &&
				!$user?.permissions?.workspace?.prompts
			) {
				goto('/');
			} else if ($page.url.pathname.includes('/tools') && !$user?.permissions?.workspace?.tools) {
				goto('/');
			} else if ($page.url.pathname.includes('/skills') && !$user?.permissions?.workspace?.skills) {
				goto('/');
			}
		}

		loaded = true;
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Workspace')} • {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<div
		class=" relative flex flex-col w-full h-screen max-h-[100dvh] transition-width duration-200 ease-in-out {$showSidebar
			? 'md:max-w-[calc(100%-var(--sidebar-width))]'
			: ''} max-w-full"
	>
		<nav class="   px-2.5 pt-1.5 backdrop-blur-xl drag-region select-none">
			<div class=" flex items-center gap-1">
				{#if $mobile}
					<div class="{$showSidebar ? 'md:hidden' : ''} self-center flex flex-none items-center">
						<Tooltip
							content={$showSidebar ? $i18n.t('Close Sidebar') : $i18n.t('Open Sidebar')}
							interactive={true}
						>
							<button
								id="sidebar-toggle-button"
								class=" cursor-pointer flex rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition cursor-"
								aria-label={$showSidebar ? $i18n.t('Close Sidebar') : $i18n.t('Open Sidebar')}
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

				<div class="">
					<div
						class="flex gap-1 scrollbar-none overflow-x-auto w-fit text-center text-sm font-medium rounded-full bg-transparent py-1 touch-auto pointer-events-auto"
					>
						<!-- Sunway: Models workspace deferred (no custom presets) — hidden for everyone incl. admins.
						     Original gate was: user.role === 'admin' OR permissions.workspace.models -->
						{#if false}
							<a
								draggable="false"
								aria-current={$page.url.pathname.includes('/workspace/models') ? 'page' : null}
								class="min-w-fit p-1.5 {$page.url.pathname.includes('/workspace/models')
									? ''
									: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition select-none"
								href="/workspace/models">{$i18n.t('Models')}</a
							>
						{/if}

						{#if $user?.role === 'admin' || $user?.permissions?.workspace?.knowledge}
							<a
								draggable="false"
								aria-current={$page.url.pathname.includes('/workspace/knowledge') ? 'page' : null}
								class="min-w-fit p-1.5 {$page.url.pathname.includes('/workspace/knowledge')
									? ''
									: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition select-none"
								href="/workspace/knowledge"
							>
								{$i18n.t('Knowledge')}
							</a>
						{/if}

						<!-- Sunway: Prompts hidden 2026-08-05 for everyone incl. admins, with the route
						     guard above. Intended target was BU-admin/user hidden + super-admin visible,
						     but no super-admin tier exists to gate on yet (see the onMount comment) — so
						     hidden from everyone until three-tier RBAC lands, then re-gate to super admin.
						     Original gate was: user.role === 'admin' OR permissions.workspace.prompts -->
						{#if false}
							<a
								draggable="false"
								aria-current={$page.url.pathname.includes('/workspace/prompts') ? 'page' : null}
								class="min-w-fit p-1.5 {$page.url.pathname.includes('/workspace/prompts')
									? ''
									: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition select-none"
								href="/workspace/prompts">{$i18n.t('Prompts')}</a
							>
						{/if}

						<!-- Sunway: Skills workspace deferred (same arbitrary-code class as Tools; named in
						     schat-ba-docs governance/decisions.md:312 as not-allowed self-service assistant
						     building) — hidden for everyone incl. admins, with the route guard above.
						     Original gate was: user.role === 'admin' OR permissions.workspace.skills -->
						{#if false}
							<a
								draggable="false"
								aria-current={$page.url.pathname.includes('/workspace/skills') ? 'page' : null}
								class="min-w-fit p-1.5 {$page.url.pathname.includes('/workspace/skills')
									? ''
									: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition select-none"
								href="/workspace/skills"
							>
								{$i18n.t('Skills')}
							</a>
						{/if}

						<!-- Sunway: Tools workspace deferred (arbitrary-code risk) — hidden for everyone incl. admins.
						     Original gate was: user.role === 'admin' OR permissions.workspace.tools -->
						{#if false}
							<a
								draggable="false"
								aria-current={$page.url.pathname.includes('/workspace/tools') ? 'page' : null}
								class="min-w-fit p-1.5 {$page.url.pathname.includes('/workspace/tools')
									? ''
									: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition select-none"
								href="/workspace/tools"
							>
								{$i18n.t('Tools')}
							</a>
						{/if}
					</div>
				</div>

				<!-- <div class="flex items-center text-xl font-medium">{$i18n.t('Workspace')}</div> -->
			</div>
		</nav>

		<div
			class="  pb-1 px-3 md:px-[18px] flex-1 max-h-full overflow-y-auto"
			id="workspace-container"
		>
			<slot />
		</div>
	</div>
{/if}
