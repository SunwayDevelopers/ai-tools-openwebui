<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { marked } from 'marked';
	import DOMPurify from 'dompurify';

	import { onMount, getContext, tick, createEventDispatcher } from 'svelte';
	import { blur, fade } from 'svelte/transition';

	const dispatch = createEventDispatcher();

	import { getChatList } from '$lib/apis/chats';
	import { updateFolderById } from '$lib/apis/folders';

	import {
		config,
		user,
		models as _models,
		temporaryChatEnabled,
		selectedFolder,
		chats,
		currentChatPage
	} from '$lib/stores';
	import { sanitizeResponseContent, extractCurlyBraceWords } from '$lib/utils';
	import { deriveFirstName, getTimeOfDay, pickNextGreetingVariant } from '$lib/utils/greeting';
	import { WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';

	import Suggestions from './Suggestions.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import EyeSlash from '$lib/components/icons/EyeSlash.svelte';
	import MessageInput from './MessageInput.svelte';
	import FolderPlaceholder from './Placeholder/FolderPlaceholder.svelte';
	import FolderTitle from './Placeholder/FolderTitle.svelte';

	const i18n = getContext('i18n');

	export let createMessagePair: Function;
	export let stopResponse: Function;

	export let autoScroll = false;

	export let atSelectedModel: Model | undefined;
	export let selectedModels: [''];

	export let history;

	export let prompt = '';
	export let files = [];
	export let messageInput = null;

	export let selectedToolIds = [];
	export let selectedSkillIds = [];
	export let selectedFilterIds = [];
	export let pendingOAuthTools = [];

	export let showCommands = false;

	export let imageGenerationEnabled = false;
	export let codeInterpreterEnabled = false;
	export let webSearchEnabled = false;

	export let onUpload: Function = (e) => {};
	export let onSelect = (e) => {};
	export let onChange = (e) => {};

	export let toolServers = [];

	export let dragged = false;

	// Sunway: rotating, time-aware greeting for the new-chat heading. Both the variant and the
	// time of day are frozen at component init — `const`, never reactive — so the heading
	// doesn't re-roll / flicker while the user types. Name derivation is conservative (see
	// utils/greeting.ts); an unsafe value falls back to a calm, name-less variant, and several
	// variants are name-less by design so the heading doesn't feel like a mail merge.
	const greetingFirstName = deriveFirstName($user?.name);
	const greetingTimeOfDay = getTimeOfDay();
	// Re-rolls on every mount. This component is inside an {#if}/{:else} that unmounts as soon
	// as the chat has messages, so "mount" == "a new empty chat was opened" — which is exactly
	// when a fresh greeting is wanted. The pick excludes whatever was shown last (sessionStorage)
	// so consecutive new chats never repeat the same line.
	const greetingVariant = pickNextGreetingVariant();

	// Maps the frozen pick onto static `$i18n.t('literal')` calls so the i18n parser extracts
	// the keys. Only reactive on language ($i18n), which never causes a name flicker.
	$: greetingText = {
		timeOfDay: greetingFirstName
			? {
					morning: $i18n.t('Good morning, {{name}}', { name: greetingFirstName }),
					afternoon: $i18n.t('Good afternoon, {{name}}', { name: greetingFirstName }),
					evening: $i18n.t('Good evening, {{name}}', { name: greetingFirstName })
				}[greetingTimeOfDay]
			: {
					morning: $i18n.t('Good morning'),
					afternoon: $i18n.t('Good afternoon'),
					evening: $i18n.t('Good evening')
				}[greetingTimeOfDay],
		welcomeBack: greetingFirstName
			? $i18n.t('Welcome back, {{name}}', { name: greetingFirstName })
			: $i18n.t('Welcome back'),
		readyWhenYouAre: greetingFirstName
			? $i18n.t('Ready when you are, {{name}}', { name: greetingFirstName })
			: $i18n.t('Ready when you are'),
		whatCanIHelpWith: $i18n.t('What can I help with?'),
		whatAreWeWorkingOn: $i18n.t('What are we working on?'),
		whereShouldWeStart: $i18n.t('Where should we start?'),
		whatsOnYourMind: $i18n.t("What's on your mind?")
	}[greetingVariant];

	let models = [];
	let selectedModelIdx = 0;

	$: if (selectedModels.length > 0) {
		selectedModelIdx = models.length - 1;
	}

	$: models = selectedModels.map((id) => $_models.find((m) => m.id === id));
</script>

<div class="m-auto w-full max-w-6xl px-2 @2xl:px-20 translate-y-6 py-24 text-center">
	{#if $temporaryChatEnabled}
		<Tooltip
			content={$i18n.t("This chat won't appear in history and your messages will not be saved.")}
			className="w-full flex justify-center mb-0.5"
			placement="top"
		>
			<div class="flex items-center gap-2 text-gray-500 text-base my-2 w-fit">
				<EyeSlash strokeWidth="2.5" className="size-4" />{$i18n.t('Temporary Chat')}
			</div>
		</Tooltip>
	{/if}

	<div
		class="w-full text-3xl text-gray-800 dark:text-gray-100 text-center flex items-center gap-4 font-primary"
	>
		<div class="w-full flex flex-col justify-center items-center">
			{#if $selectedFolder}
				<FolderTitle
					folder={$selectedFolder}
					onUpdate={async (folder) => {
						await chats.set(await getChatList(localStorage.token, $currentChatPage));
						currentChatPage.set(1);
					}}
					onDelete={async () => {
						await chats.set(await getChatList(localStorage.token, $currentChatPage));
						currentChatPage.set(1);

						selectedFolder.set(null);
					}}
				/>
			{:else}
				<div class="flex flex-row justify-center gap-2.5 @sm:gap-3 w-fit px-5 max-w-xl">
					<div class="flex shrink-0 justify-center">
						<!-- Sunway: one avatar, not one per selected model. Every schat model resolves to
						     the same brand icon (the red S), so upstream's overlapping per-model stack
						     rendered N identical icons as soon as a second model was added with "+".
						     Deduping by image is impossible client-side: /api/models strips
						     meta.profile_image_url (backend/open_webui/main.py), so the frontend only
						     ever has a per-model-id URL. The fix is to stop stacking. Restore upstream
						     by iterating `models` instead of its first entry. -->
						<div class="flex -space-x-4 mb-0.5" in:fade={{ duration: 100 }}>
							{#each models.slice(0, 1) as model, modelIdx}
								<Tooltip
									content={(models[modelIdx]?.info?.meta?.tags ?? [])
										.map((tag) => tag.name.toUpperCase())
										.join(', ')}
									placement="top"
								>
									<button
										aria-hidden={models.length <= 1}
										aria-label={$i18n.t('Get information on {{name}} in the UI', {
											name: models[modelIdx]?.name
										})}
										on:click={() => {
											selectedModelIdx = modelIdx;
										}}
									>
										<img
											src={`${WEBUI_API_BASE_URL}/models/model/profile/image?id=${model?.id}&lang=${$i18n.language}`}
											class=" size-9 @sm:size-10 rounded-full border-[1px] border-gray-100 dark:border-none"
											aria-hidden="true"
											draggable="false"
											on:error={(e) => {
												e.currentTarget.src = '/favicon.png';
											}}
										/>
									</button>
								</Tooltip>
							{/each}
						</div>
					</div>

					<div
						class=" text-3xl @sm:text-3xl line-clamp-1 flex items-center"
						in:fade={{ duration: 100 }}
					>
						<!-- Sunway: greeting is the hero heading, unconditionally. The model name
						is redundant here — it's already in the navbar model selector and the avatar
						row above — and putting it here hid the greeting whenever a model was selected
						(i.e. always). Hover an avatar or open the navbar dropdown to see the model. -->
						<span class="line-clamp-1">
							{greetingText}
						</span>
					</div>
				</div>

				<div class="flex mt-1 mb-2">
					<div in:fade={{ duration: 100, delay: 50 }}>
						{#if models[selectedModelIdx]?.info?.meta?.description ?? null}
							<Tooltip
								className=" w-fit"
								content={DOMPurify.sanitize(
									marked.parse(
										sanitizeResponseContent(
											models[selectedModelIdx]?.info?.meta?.description ?? ''
										).replaceAll('\n', '<br>')
									)
								)}
								placement="top"
							>
								<div
									class="mt-0.5 px-2 text-sm font-normal text-gray-500 dark:text-gray-400 line-clamp-2 max-w-xl markdown"
								>
									{@html DOMPurify.sanitize(
										marked.parse(
											sanitizeResponseContent(
												models[selectedModelIdx]?.info?.meta?.description ?? ''
											).replaceAll('\n', '<br>')
										)
									)}
								</div>
							</Tooltip>

							{#if models[selectedModelIdx]?.info?.meta?.user}
								<div class="mt-0.5 text-sm font-normal text-gray-400 dark:text-gray-500">
									By
									{#if models[selectedModelIdx]?.info?.meta?.user.community}
										<a
											href="https://openwebui.com/m/{models[selectedModelIdx]?.info?.meta?.user
												.username}"
											>{models[selectedModelIdx]?.info?.meta?.user.name
												? models[selectedModelIdx]?.info?.meta?.user.name
												: `@${models[selectedModelIdx]?.info?.meta?.user.username}`}</a
										>
									{:else}
										{models[selectedModelIdx]?.info?.meta?.user.name}
									{/if}
								</div>
							{/if}
						{/if}
					</div>
				</div>
			{/if}

			<div class="text-base font-normal @md:max-w-3xl w-full py-3 {atSelectedModel ? 'mt-2' : ''}">
				<MessageInput
					bind:this={messageInput}
					{history}
					bind:selectedModels
					bind:files
					bind:prompt
					bind:autoScroll
					bind:selectedToolIds
					bind:selectedSkillIds
					bind:selectedFilterIds
					bind:imageGenerationEnabled
					bind:codeInterpreterEnabled
					bind:webSearchEnabled
					bind:atSelectedModel
					bind:showCommands
					bind:dragged
					{pendingOAuthTools}
					{toolServers}
					{stopResponse}
					{createMessagePair}
					placeholder={$i18n.t('How can I help you today?')}
					{onChange}
					{onUpload}
					on:submit={(e) => {
						dispatch('submit', e.detail);
					}}
				/>
			</div>
		</div>
	</div>

	{#if $selectedFolder}
		<div
			class="mx-auto px-4 md:max-w-3xl md:px-6 font-primary min-h-62"
			in:fade={{ duration: 200, delay: 200 }}
		>
			<FolderPlaceholder folder={$selectedFolder} />
		</div>
	{:else}
		<div class="mx-auto max-w-2xl font-primary mt-2" in:fade={{ duration: 200, delay: 200 }}>
			<div class="mx-5">
				<Suggestions
					suggestionPrompts={atSelectedModel?.info?.meta?.suggestion_prompts ??
						models[selectedModelIdx]?.info?.meta?.suggestion_prompts ??
						$config?.default_prompt_suggestions ??
						[]}
					inputValue={prompt}
					{onSelect}
				/>
			</div>
		</div>
	{/if}
</div>
