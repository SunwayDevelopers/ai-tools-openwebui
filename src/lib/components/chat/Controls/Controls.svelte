<script lang="ts">
	import { createEventDispatcher, getContext, onDestroy } from 'svelte';
	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	import { fade } from 'svelte/transition';

	import XMark from '$lib/components/icons/XMark.svelte';
	import AdvancedParams from '../Settings/Advanced/AdvancedParams.svelte';
	import Valves from '$lib/components/chat/Controls/Valves.svelte';
	import FileItem from '$lib/components/common/FileItem.svelte';
	import Collapsible from '$lib/components/common/Collapsible.svelte';

	import { user, settings, chatControlsSavedAt } from '$lib/stores';
	export let models = [];
	export let chatFiles = [];
	export let params = {};
	export let embed = false;

	// Persist collapsible section open/close state
	const getOpen = (key: string, fallback = true): boolean => {
		const v = localStorage.getItem(`chatControls.${key}`);
		return v !== null ? v === 'true' : fallback;
	};
	const setOpen = (key: string) => (open: boolean) => {
		localStorage.setItem(`chatControls.${key}`, String(open));
	};

	let showFiles = getOpen('files');
	let showValves = getOpen('valves', false);
	let showSystemPrompt = getOpen('systemPrompt');
	let showAdvancedParams = getOpen('advancedParams');

	// Sunway: autosave "Saved" pill for the per-chat System Prompt. Chat.saveControls bumps
	// chatControlsSavedAt after a real persisted save (temporary chats stay silent), so this is
	// honest reassurance. Initialised to the current value so it never flashes on mount.
	let lastSavedAt = $chatControlsSavedAt;
	let savedVisible = false;
	let savedTimer;
	$: if ($chatControlsSavedAt && $chatControlsSavedAt !== lastSavedAt) {
		lastSavedAt = $chatControlsSavedAt;
		savedVisible = true;
		clearTimeout(savedTimer);
		savedTimer = setTimeout(() => (savedVisible = false), 1500);
	}
	onDestroy(() => clearTimeout(savedTimer));
</script>

<div class=" dark:text-white">
	{#if !embed}
		<div class=" flex items-center justify-between dark:text-gray-100 mb-2">
			<div class=" text-md self-center font-primary">{$i18n.t('Controls')}</div>
			<button
				class="self-center"
				aria-label={$i18n.t('Close chat controls')}
				on:click={() => {
					dispatch('close');
				}}
			>
				<XMark className="size-3.5" />
			</button>
		</div>
	{/if}

	{#if $user?.role === 'admin' || ($user?.permissions.chat?.controls ?? true)}
		<div class=" dark:text-gray-200 text-sm py-0.5 px-0.5">
			<!-- Sunway: chat-file list hidden — per-chat Controls re-enabled for System Prompt only (see CLAUDE.md). -->
			{#if false && chatFiles.length > 0}
				<Collapsible
					title={$i18n.t('Files')}
					bind:open={showFiles}
					onChange={setOpen('files')}
					buttonClassName="w-full"
				>
					<div class="flex flex-col gap-1 mt-1.5" slot="content">
						{#each chatFiles as file, fileIdx}
							<FileItem
								className="w-full"
								item={file}
								edit={true}
								url={file?.url ? file.url : null}
								name={file.name}
								type={file.type}
								size={file?.size}
								dismissible={true}
								small={true}
								on:dismiss={() => {
									// Remove the file from the chatFiles array

									chatFiles.splice(fileIdx, 1);
									chatFiles = chatFiles;
								}}
								on:click={() => {
									console.log(file);
								}}
							/>
						{/each}
					</div>
				</Collapsible>

				<hr class="my-2 border-gray-50 dark:border-gray-700/10" />
			{/if}

			<!-- Sunway: Valves hidden — per-chat Controls re-enabled for System Prompt only (see CLAUDE.md). -->
			{#if false && ($user?.role === 'admin' || ($user?.permissions.chat?.valves ?? true))}
				<Collapsible
					bind:open={showValves}
					onChange={setOpen('valves')}
					title={$i18n.t('Valves')}
					buttonClassName="w-full"
				>
					<div class="text-sm" slot="content">
						<Valves show={showValves} />
					</div>
				</Collapsible>

				<hr class="my-2 border-gray-50 dark:border-gray-700/10" />
			{/if}

			{#if $user?.role === 'admin' || ($user?.permissions.chat?.system_prompt ?? true)}
				<!-- Sunway: slot-mode header so the autosave "Saved" pill can sit beside the title. -->
				<Collapsible
					bind:open={showSystemPrompt}
					onChange={setOpen('systemPrompt')}
					buttonClassName="w-full"
					chevron={true}
				>
					<div class="flex items-center gap-2">
						<span>{$i18n.t('System Prompt')}</span>
						{#if savedVisible}
							<span
								transition:fade={{ duration: 150 }}
								class="inline-flex items-center gap-0.5 text-xs font-medium text-green-600 dark:text-green-400"
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 20 20"
									fill="currentColor"
									class="size-3.5"
								>
									<path
										fill-rule="evenodd"
										d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z"
										clip-rule="evenodd"
									/>
								</svg>
								{$i18n.t('Saved')}
							</span>
						{/if}
					</div>
					<div class="" slot="content">
						<textarea
							bind:value={params.system}
							class="w-full text-xs outline-hidden resize-vertical {$settings.highContrastMode
								? 'border-2 border-gray-300 dark:border-gray-700 rounded-lg bg-gray-50 dark:bg-gray-800 p-2.5'
								: 'py-1.5 bg-transparent'}"
							rows="4"
							placeholder={$i18n.t('Enter system prompt')}
						/>
					</div>
				</Collapsible>

				<!-- Sunway: divider removed — System Prompt is the last visible Controls section now. -->
			{/if}

			<!-- Sunway: Advanced Params hidden — per-chat Controls re-enabled for System Prompt only (see CLAUDE.md). -->
			{#if false && ($user?.role === 'admin' || ($user?.permissions.chat?.params ?? true))}
				<Collapsible
					title={$i18n.t('Advanced Params')}
					bind:open={showAdvancedParams}
					onChange={setOpen('advancedParams')}
					buttonClassName="w-full"
				>
					<div class="text-sm mt-1.5" slot="content">
						<div>
							<AdvancedParams admin={$user?.role === 'admin'} custom={true} bind:params />
						</div>
					</div>
				</Collapsible>
			{/if}
		</div>
	{/if}
</div>
