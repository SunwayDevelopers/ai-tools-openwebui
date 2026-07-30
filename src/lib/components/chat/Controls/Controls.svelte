<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	import XMark from '$lib/components/icons/XMark.svelte';
	import AdvancedParams from '../Settings/Advanced/AdvancedParams.svelte';
	import Valves from '$lib/components/chat/Controls/Valves.svelte';
	import FileItem from '$lib/components/common/FileItem.svelte';
	import Collapsible from '$lib/components/common/Collapsible.svelte';
	import Check from '$lib/components/icons/Check.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	import { user, settings, config, chatControlsSaveState } from '$lib/stores';

	// Sunway: char budget for the per-chat System Prompt, served by /api/config so the UI
	// and the backend truncation agree on one number. 0 = uncapped.
	$: systemPromptMaxChars = $config?.chat_system_prompt_max_chars ?? 0;
	export let models = [];
	export let chatFiles = [];
	export let params = {};
	export let embed = false;

	// Sunway: persist the System Prompt immediately / retry a failed save (wired from Chat.svelte).
	export let onSave: () => void = () => {};

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

	// Sunway: the per-chat System Prompt Save button reads chatControlsSaveState (owned by
	// Chat.svelte): idle/saved → "Saved ✓" (disabled), dirty → clickable "Save", saving →
	// spinner, error → clickable "Couldn't save — Retry". Autosave still runs underneath;
	// the button just flushes it on demand and gives constant, visible confirmation.
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
					<!-- Sunway: always-visible Save button for the per-chat System Prompt. There's
					no commit boundary (the text is the live request payload, so it applies to the
					next message regardless) — the button gives impatient users a tangible action +
					confirmation, and clicking flushes the debounced autosave immediately. Clickable
					only when there's something to do (dirty / error). -->
					<!-- Sunway a11y: the save affordance is two different things depending on state,
					so it's rendered as two different elements rather than one button that is
					disabled most of the time. "Save" / "Retry" are actionable -> <button>. "Saving",
					"Saved" and "Applies to your next message" are status -> role="status", which
					screen readers announce as a live update instead of "dimmed button, Saved". -->
					<div class="flex items-center gap-2">
						<span>{$i18n.t('System Prompt')}</span>

						{#if $chatControlsSaveState === 'dirty' || $chatControlsSaveState === 'error'}
							<button
								type="button"
								on:pointerup|stopPropagation={() => {
									onSave();
								}}
								class="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium transition cursor-pointer {$chatControlsSaveState ===
								'error'
									? 'text-red-600 dark:text-red-400 hover:bg-red-500/10'
									: 'text-blue-600 dark:text-blue-400 hover:bg-blue-500/10'}"
							>
								{#if $chatControlsSaveState === 'error'}
									{$i18n.t("Couldn't save — Retry")}
								{:else}
									{$i18n.t('Save')}
								{/if}
							</button>
						{:else}
							<span
								role="status"
								aria-live="polite"
								class="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium {$chatControlsSaveState ===
								'saved'
									? 'text-green-600 dark:text-green-400'
									: 'text-gray-400 dark:text-gray-500'}"
							>
								{#if $chatControlsSaveState === 'saving'}
									<Spinner className="size-3" />
									{$i18n.t('Saving...')}
								{:else if $chatControlsSaveState === 'unsaved'}
									<!-- Sunway: new/unpersisted chat. No "Saved ✓" — the prompt isn't saved
									yet, it just applies to (and persists with) the next message. Only shown
									once there's actually a prompt to reassure about. -->
									{#if params.system?.trim()}
										{$i18n.t('Applies to your next message')}
									{/if}
								{:else}
									<!-- 'saved' and 'idle' both land here, matching the previous behaviour;
									only the colour distinguishes a just-completed save from a quiet chat. -->
									<Check className="size-3.5" strokeWidth="2.5" />
									{$i18n.t('Saved')}
								{/if}
							</span>
						{/if}
					</div>
					<div class="" slot="content">
						<textarea
							bind:value={params.system}
							maxlength={systemPromptMaxChars > 0 ? systemPromptMaxChars : null}
							class="w-full text-xs outline-hidden resize-vertical {$settings.highContrastMode
								? 'border-2 border-gray-300 dark:border-gray-700 rounded-lg bg-gray-50 dark:bg-gray-800 p-2.5'
								: 'py-1.5 bg-transparent'}"
							rows="4"
							placeholder={$i18n.t('Enter system prompt')}
						/>

						<!-- Sunway: the field is re-sent on every turn of the chat, so it's budgeted
						rather than unbounded. The counter only appears once the user is near the
						limit — showing "0 / 4000" under an empty box just makes a preferences field
						look like a form with a quota. The backend truncates at the same number, so
						this stops them at the limit instead of silently trimming afterwards. -->
						{#if systemPromptMaxChars > 0 && (params.system?.length ?? 0) > systemPromptMaxChars * 0.8}
							<div class="flex justify-end">
								<span
									class="text-[10px] {(params.system?.length ?? 0) >= systemPromptMaxChars
										? 'text-red-500'
										: 'text-gray-400 dark:text-gray-500'}"
								>
									{params.system?.length ?? 0} / {systemPromptMaxChars}
								</span>
							</div>
						{/if}
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
