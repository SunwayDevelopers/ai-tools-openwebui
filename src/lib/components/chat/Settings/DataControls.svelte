<script lang="ts">
	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import {
		chatId,
		chats,
		user,
		settings,
		scrollPaginationEnabled,
		currentChatPage,
		pinnedChats,
		config
	} from '$lib/stores';

	import {
		archiveAllChats,
		deleteAllChats,
		getAllChats,
		getChatList,
		getPinnedChatList
	} from '$lib/apis/chats';
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import ArchivedChatsModal from '$lib/components/layout/ArchivedChatsModal.svelte';
	import SharedChatsModal from '$lib/components/layout/SharedChatsModal.svelte';
	import FilesModal from '$lib/components/layout/FilesModal.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';

	const i18n = getContext('i18n');

	export let saveSettings: Function;

	// Chats

	let showArchiveConfirmDialog = false;
	let showDeleteConfirmDialog = false;
	let showArchivedChatsModal = false;
	let showSharedChatsModal = false;
	let showFilesModal = false;

	// Sunway: importChatsHandler() was removed here (hardening plan). POST /chats/import is
	// deleted -- it bypassed MAX_CHATS_PER_USER, which is enforced only at /chats/new and on
	// the completion path. Exporting your OWN chats is unaffected.

	const exportChats = async () => {
		let blob = new Blob([JSON.stringify(await getAllChats(localStorage.token))], {
			type: 'application/json'
		});
		saveAs(blob, `chat-export-${Date.now()}.json`);
	};

	const archiveAllChatsHandler = async () => {
		await goto('/');
		await archiveAllChats(localStorage.token).catch((error) => {
			toast.error(`${error}`);
		});

		currentChatPage.set(1);
		await chats.set(await getChatList(localStorage.token, $currentChatPage));
		pinnedChats.set([]);
		scrollPaginationEnabled.set(true);
	};

	const deleteAllChatsHandler = async () => {
		await goto('/');
		await deleteAllChats(localStorage.token).catch((error) => {
			toast.error(`${error}`);
		});

		currentChatPage.set(1);
		await chats.set(await getChatList(localStorage.token, $currentChatPage));
		scrollPaginationEnabled.set(true);
	};

	const handleArchivedChatsChange = async () => {
		currentChatPage.set(1);
		await chats.set(await getChatList(localStorage.token, $currentChatPage));

		scrollPaginationEnabled.set(true);
	};
</script>

<ArchivedChatsModal
	bind:show={showArchivedChatsModal}
	onUpdate={handleArchivedChatsChange}
	onDelete={(id) => {
		if ($chatId === id) {
			goto('/');
			chatId.set('');
		}
	}}
/>
<SharedChatsModal bind:show={showSharedChatsModal} />
<FilesModal bind:show={showFilesModal} />

<ConfirmDialog
	title={$i18n.t('Archive All Chats')}
	message={$i18n.t('Are you sure you want to archive all chats? This action cannot be undone.')}
	bind:show={showArchiveConfirmDialog}
	on:confirm={archiveAllChatsHandler}
	on:cancel={() => {
		showArchiveConfirmDialog = false;
	}}
/>

<ConfirmDialog
	title={$i18n.t('Delete All Chats')}
	message={$i18n.t('Are you sure you want to delete all chats? This action cannot be undone.')}
	bind:show={showDeleteConfirmDialog}
	on:confirm={deleteAllChatsHandler}
	on:cancel={() => {
		showDeleteConfirmDialog = false;
	}}
/>

<div id="tab-chats" class="flex flex-col h-full justify-between text-sm">
	<div class="space-y-3 overflow-y-scroll max-h-[28rem] md:max-h-full">
		<div>
			<div class="mb-1 text-sm font-medium">{$i18n.t('Chats')}</div>

			<!-- Sunway: "Import Chats" was deleted here (hardening plan). It was already hidden
			     because imports bypassed the 30-chat cap; the endpoint is now gone too, so the
			     bypass is closed by construction rather than by hiding a button. -->

			<!-- Sunway: bulk JSON "Export Chats" hidden for everyone incl. admins — dev/portability
			     format (not human-readable) and a dead-end now that Import is hidden. The useful
			     per-chat readable download (PDF/TXT/JSON) in the chat menu stays. Code kept, gated
			     off (replaced the chat.export permission gate, which admins bypassed). See CLAUDE.md. -->
			{#if false}
				<div>
					<div class="py-0.5 flex w-full justify-between">
						<div class="self-center text-xs">{$i18n.t('Export Chats')}</div>
						<button
							class="p-1 px-3 text-xs flex rounded-sm transition"
							on:click={() => {
								exportChats();
							}}
							type="button"
						>
							<span class="self-center">{$i18n.t('Export')}</span>
						</button>
					</div>
				</div>
			{/if}

			{#if $config?.enable_chat_archive ?? false}
				<div>
					<div class="py-0.5 flex w-full justify-between">
						<div class="self-center text-xs">{$i18n.t('Archived Chats')}</div>
						<button
							class="p-1 px-3 text-xs flex rounded-sm transition"
							on:click={() => {
								showArchivedChatsModal = true;
							}}
							type="button"
						>
							<span class="self-center">{$i18n.t('Manage')}</span>
						</button>
					</div>
				</div>
			{/if}

			<div>
				<div class="py-0.5 flex w-full justify-between">
					<div class="self-center text-xs">{$i18n.t('Shared Chats')}</div>
					<button
						class="p-1 px-3 text-xs flex rounded-sm transition"
						on:click={() => {
							showSharedChatsModal = true;
						}}
						type="button"
					>
						<span class="self-center">{$i18n.t('Manage')}</span>
					</button>
				</div>
			</div>

			{#if $config?.enable_chat_archive ?? false}
				<div>
					<div class="py-0.5 flex w-full justify-between">
						<div class="self-center text-xs">{$i18n.t('Archive All Chats')}</div>
						<button
							class="p-1 px-3 text-xs flex rounded-sm transition"
							on:click={() => {
								showArchiveConfirmDialog = true;
							}}
							type="button"
						>
							<span class="self-center">{$i18n.t('Archive All')}</span>
						</button>
					</div>
				</div>
			{/if}

			<div>
				<div class="py-0.5 flex w-full justify-between">
					<div class="self-center text-xs">{$i18n.t('Delete All Chats')}</div>
					<button
						class="p-1 px-3 text-xs flex rounded-sm transition"
						on:click={() => {
							showDeleteConfirmDialog = true;
						}}
						type="button"
					>
						<span class="self-center">{$i18n.t('Delete All')}</span>
					</button>
				</div>
			</div>
		</div>

		<!-- Sunway: personal file-management surface deferred (no persistent user memory).
		     Hidden for everyone incl. admins; kept in code, gated off. Flip to re-enable. -->
		{#if false}
			<div>
				<div class="mb-1 text-sm font-medium">{$i18n.t('Files')}</div>

				<div>
					<div class="py-0.5 flex w-full justify-between">
						<div class="self-center text-xs">{$i18n.t('Manage Files')}</div>
						<button
							class="p-1 px-3 text-xs flex rounded-sm transition"
							on:click={() => {
								showFilesModal = true;
							}}
							type="button"
						>
							<span class="self-center">{$i18n.t('Manage')}</span>
						</button>
					</div>
				</div>
			</div>
		{/if}
	</div>
</div>
