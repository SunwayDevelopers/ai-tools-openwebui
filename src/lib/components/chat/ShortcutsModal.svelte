<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import Modal from '../common/Modal.svelte';
	import { shortcuts } from '$lib/shortcuts';
	import { config, settings } from '$lib/stores';
	import ShortcutItem from './ShortcutItem.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	type CategorizedShortcuts = {
		[category: string]: {
			left: Shortcut[];
			right: Shortcut[];
		};
	};

	const i18n = getContext('i18n');

	export let show = false;

	let categorizedShortcuts: CategorizedShortcuts = {};
	let isMac = false;

	onMount(() => {
		isMac = /Mac/i.test(navigator.userAgent);
	});

	// Sunway: voice (STT/TTS/Call) is deferred (ENABLE_VOICE=false) — hide its shortcuts too.
	const VOICE_SHORTCUT_IDS = ['toggleDictation', 'toggleMute'];

	// Sunway: de-clutter the shortcuts help for the internal rollout — these entries are
	// power-user / conditional shortcuts that confuse more than they help. The key handlers
	// themselves stay active (they are harmless local UI actions; Esc in particular must keep
	// working to close modals / stop generation) — EXCEPT Generate Message Pair and Add Custom
	// Prompt, whose handlers are ALSO disabled (Generate Message Pair fabricates an assistant
	// turn; the `/` prompt palette is deferred — see CLAUDE.md and chat/MessageInput.svelte).
	const HIDDEN_SHORTCUT_IDS = [
		'copyLastCodeBlock',
		'generateMessagePair',
		'acceptAutocomplete',
		'preventFileCreation',
		'focusInput',
		'closeModal',
		'addPrompt'
	];

	$: {
		const allShortcuts = Object.entries(shortcuts)
			.filter(([id, shortcut]) => {
				if (HIDDEN_SHORTCUT_IDS.includes(id)) {
					return false;
				}
				if (!($config?.enable_voice ?? false) && VOICE_SHORTCUT_IDS.includes(id)) {
					return false;
				}
				// Sunway: Temporary Chat hidden for the rollout (ENABLE_TEMPORARY_CHAT=false) —
				// its handler is gated too, so drop the listing entirely. See CLAUDE.md.
				if (!($config?.enable_temporary_chat ?? false) && id === 'newTemporaryChat') {
					return false;
				}
				if (!shortcut.setting) {
					return true;
				}
				return $settings[shortcut.setting.id] === shortcut.setting.value;
			})
			.map(([, shortcut]) => shortcut);

		categorizedShortcuts = allShortcuts.reduce((acc, shortcut) => {
			const category = shortcut.category;
			if (!acc[category]) {
				acc[category] = [];
			}
			acc[category].push(shortcut);
			return acc;
		}, {});
	}
</script>

<Modal bind:show>
	<div class="text-gray-700 dark:text-gray-100 px-5 py-4">
		<div class="flex justify-between dark:text-gray-300 pb-2">
			<div class="text-lg font-medium self-center">{$i18n.t('Keyboard Shortcuts')}</div>
			<button class="self-center" aria-label={$i18n.t('Close')} on:click={() => (show = false)}>
				<XMark className={'size-5'} />
			</button>
		</div>

		{#each Object.entries(categorizedShortcuts) as [category, items], categoryIndex}
			{#if categoryIndex > 0}
				<div class="py-3">
					<div class="w-full border-t dark:border-gray-850 border-gray-50" />
				</div>
			{/if}

			<div class="flex justify-between dark:text-gray-300 pb-2">
				<div class="text-base self-center">{$i18n.t(category)}</div>
			</div>
			<div class="flex flex-col md:flex-row w-full md:space-x-2 dark:text-gray-200">
				<div class="flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
					<div class=" grid grid-cols-1 sm:grid-cols-2 gap-2 gap-x-4 w-full">
						<!-- {$i18n.t('Chat')} -->
						<!-- {$i18n.t('Global')} -->
						<!-- {$i18n.t('Input')} -->
						<!-- {$i18n.t('Message')} -->

						<!-- {$i18n.t('New Chat')} -->
						<!-- {$i18n.t('New Temporary Chat')} -->
						<!-- {$i18n.t('Delete Chat')} -->
						<!-- {$i18n.t('Open Model Selector')} -->
						<!-- {$i18n.t('Toggle Dictation')} -->
						<!-- {$i18n.t('Search')} -->
						<!-- {$i18n.t('Open Settings')} -->
						<!-- {$i18n.t('Show Shortcuts')} -->
						<!-- {$i18n.t('Toggle Sidebar')} -->
						<!-- {$i18n.t('Close Modal')} -->
						<!-- {$i18n.t('Focus Chat Input')} -->
						<!-- {$i18n.t('Accept Autocomplete Generation\nJump to Prompt Variable')} -->
						<!-- {$i18n.t('Prevent File Creation')} -->
						<!-- {$i18n.t('Attach File From Knowledge')} -->
						<!-- {$i18n.t('Add Custom Prompt')} -->
						<!-- {$i18n.t('Talk to Model')} -->
						<!-- {$i18n.t('Generate Message Pair')} -->
						<!-- {$i18n.t('Regenerate Response')} -->
						<!-- {$i18n.t('Stop Generating')} -->
						<!-- {$i18n.t('Edit Last Message')} -->
						<!-- {$i18n.t('Copy Last Response')} -->
						<!-- {$i18n.t('Copy Last Code Block')} -->

						<!-- {$i18n.t('Only active when "Paste Large Text as File" setting is toggled on.')} -->
						<!-- {$i18n.t('Only active when the chat input is in focus.')} -->
						<!-- {$i18n.t('Only active when the chat input is in focus and an LLM is generating a response.')} -->
						<!-- {$i18n.t('Only can be triggered when the chat input is in focus.')} -->

						<!-- {$i18n.t('Voice')} -->
						<!-- {$i18n.t('Toggle Mute')} -->
						<!-- {$i18n.t('Only active during Voice Mode.')} -->
						{#each items as shortcut}
							<div class="col-span-1 flex items-start">
								<ShortcutItem {shortcut} {isMac} />
							</div>
						{/each}
					</div>
				</div>
			</div>
		{/each}
	</div>
</Modal>

<style>
	input::-webkit-outer-spin-button,
	input::-webkit-inner-spin-button {
		-webkit-appearance: none;
		margin: 0;
	}

	.tabs::-webkit-scrollbar {
		display: none;
	}

	.tabs {
		-ms-overflow-style: none;
		scrollbar-width: none;
	}

	input[type='number'] {
		-moz-appearance: textfield;
	}
</style>
