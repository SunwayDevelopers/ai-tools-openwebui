<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { WEBUI_NAME, showSidebar, functions, mobile } from '$lib/stores';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Sidebar from '$lib/components/icons/Sidebar.svelte';

	const i18n = getContext('i18n');

	let loaded = false;

	onMount(async () => {
		// Sunway: Playground is deferred and hidden for EVERYONE incl. admins (see CLAUDE.md →
		// "Deferred / hidden features"). Same pattern as Workspace → Models/Tools/Skills: block
		// direct-URL access so there is no admin back-door into the hidden screen. The nav entries
		// live in layout/Sidebar/UserMenu.svelte and layout/Sidebar.svelte. `loaded` is deliberately
		// never set so the page never paints while the redirect resolves. Reverse by removing this
		// redirect and setting `loaded = true` instead.
		await goto('/');
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Playground')} • {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<div
		class=" flex flex-col w-full h-screen max-h-[100dvh] transition-width duration-200 ease-in-out {$showSidebar
			? 'md:max-w-[calc(100%-var(--sidebar-width))]'
			: ''} max-w-full"
	>
		<nav class="   px-2.5 pt-1.5 backdrop-blur-xl w-full drag-region select-none">
			<div class=" flex items-center">
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
							class="min-w-fit p-1.5 {['/playground', '/playground/'].includes($page.url.pathname)
								? ''
								: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition select-none"
							href="/playground">{$i18n.t('Chat')}</a
						>

						<!-- <a
						class="min-w-fit p-1.5 {$page.url.pathname.includes('/playground/notes')
							? ''
							: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition"
						href="/playground/notes">{$i18n.t('Notes')}</a
					> -->

						<a
							draggable="false"
							class="min-w-fit p-1.5 {$page.url.pathname.includes('/playground/completions')
								? ''
								: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition select-none"
							href="/playground/completions">{$i18n.t('Completions')}</a
						>

						<a
							draggable="false"
							class="min-w-fit p-1.5 {$page.url.pathname.includes('/playground/images')
								? ''
								: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition select-none"
							href="/playground/images">{$i18n.t('Images')}</a
						>
					</div>
				</div>
			</div>
		</nav>

		<div class=" flex-1 max-h-full overflow-y-auto">
			<slot />
		</div>
	</div>
{/if}
