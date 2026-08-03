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

	const i18n = getContext('i18n');

	let loaded = false;

	onMount(async () => {
		// Sunway: Models, Tools & Skills workspace are deferred and hidden for EVERYONE incl.
		// admins (see CLAUDE.md → "Deferred / hidden features"). Block direct-URL access too,
		// so there is no admin back-door into the deferred screens. Reverse by removing this.
		//
		// Skills added 2026-07-31: same arbitrary-code class as Tools, and named in the BA
		// record's not-allowed list — schat-ba-docs governance/decisions.md:312 rules out
		// "model customizations / presets / prompt templates / skills that let users or
		// BU-admin groups build their own assistants ... for anyone". Prompts and Functions
		// are deliberately NOT here: AUDIT-020 keeps Prompts admin-curated (they are text
		// snippets, they do not touch the model), and Functions carry the inlet/outlet filter
		// hooks that the guardrail work depends on. See sunway-schat-notes.md §1.
		if (
			$page.url.pathname.includes('/workspace/models') ||
			$page.url.pathname.includes('/workspace/tools') ||
			$page.url.pathname.includes('/workspace/skills')
		) {
			await goto('/');
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

						{#if $user?.role === 'admin' || $user?.permissions?.workspace?.prompts}
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
