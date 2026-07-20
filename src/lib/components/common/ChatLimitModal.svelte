<script lang="ts">
	// Sunway retention cap UX: shown when a user clicks "New Chat" while already at
	// MAX_CHATS_PER_USER. Lets them sort + multi-select + delete existing chats to
	// free a slot, then start a new chat. The backend enforces the cap independently
	// (main.py completion handler + /chats/new) — this is the UX layer only.
	import { getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import { getChatList, deleteChatById } from '$lib/apis/chats';
	import Spinner from './Spinner.svelte';

	const i18n = getContext('i18n');

	export let show = false;
	export let maxChats = 0;
	// Called after deletions so the sidebar can refresh its list + counter.
	export let onUpdate: () => void = () => {};

	let chats = [];
	let selected = new Set();
	let loading = false;
	let deleting = false;
	let sortOrder: 'oldest' | 'newest' = 'oldest';
	let loadedForShow = false;

	$: count = chats.length;
	$: overCap = maxChats > 0 && count >= maxChats;
	$: sortedChats = [...chats].sort((a, b) =>
		sortOrder === 'oldest'
			? (a.updated_at ?? 0) - (b.updated_at ?? 0)
			: (b.updated_at ?? 0) - (a.updated_at ?? 0)
	);

	// Load once each time the modal opens; reset when it closes.
	$: if (show && !loadedForShow) {
		loadedForShow = true;
		loadChats();
	}
	$: if (!show) {
		loadedForShow = false;
	}

	const loadChats = async () => {
		loading = true;
		selected = new Set();
		try {
			// include_pinned=true: the retention cap counts pinned chats too, so surface
			// them here or a user who pinned many chats couldn't free a slot. (Chat Archive
			// is disabled in schat — ENABLE_CHAT_ARCHIVE=false — so archived chats aren't a
			// factor.) The cap is small (tens), so page 1 (+ a defensive page 2) covers it.
			const page1 = (await getChatList(localStorage.token, 1, true)) ?? [];
			const page2 =
				page1.length >= 60 ? ((await getChatList(localStorage.token, 2, true)) ?? []) : [];
			chats = [...page1, ...page2];
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			loading = false;
		}
	};

	const toggle = (id) => {
		if (selected.has(id)) {
			selected.delete(id);
		} else {
			selected.add(id);
		}
		selected = new Set(selected); // reassign to trigger reactivity
	};

	const deleteSelected = async () => {
		if (selected.size === 0 || deleting) {
			return;
		}
		deleting = true;
		let ok = 0;
		for (const id of selected) {
			try {
				await deleteChatById(localStorage.token, id);
				ok += 1;
			} catch (e) {
				toast.error(`${e}`);
			}
		}
		deleting = false;
		if (ok > 0) {
			toast.success($i18n.t('Deleted {{n}} chat(s)', { n: ok }));
			onUpdate();
			await loadChats();
		}
	};

	const startNewChat = () => {
		show = false;
		goto('/');
	};
</script>

{#if show}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		class="fixed inset-0 z-9999 flex items-center justify-center bg-black/50 p-4"
		role="dialog"
		aria-modal="true"
		on:mousedown|self={() => (show = false)}
	>
		<div
			class="flex max-h-[80vh] w-full max-w-lg flex-col rounded-2xl border border-gray-100 bg-white shadow-3xl dark:border-gray-850 dark:bg-gray-900"
			on:mousedown|stopPropagation
		>
			<div class="px-5 pt-5 pb-3">
				<div class="text-lg font-medium text-gray-900 dark:text-white">
					{$i18n.t('Chat limit reached')}
				</div>
				<div class="mt-1 text-sm text-gray-500 dark:text-gray-400">
					{$i18n.t('You have {{count}} of {{max}} chats. Delete one or more to start a new chat.', {
						count,
						max: maxChats
					})}
				</div>
			</div>

			<div class="flex items-center justify-between px-5 pb-2">
				<span class="text-xs font-medium {overCap ? 'text-red-500' : 'text-gray-400'}">
					{count} / {maxChats}
				</span>
				<div class="flex items-center gap-2 text-xs">
					<span class="text-gray-400">{$i18n.t('Sort')}</span>
					<select
						bind:value={sortOrder}
						class="rounded-lg bg-transparent text-gray-600 outline-none dark:text-gray-300"
					>
						<option value="oldest">{$i18n.t('Oldest first')}</option>
						<option value="newest">{$i18n.t('Newest first')}</option>
					</select>
				</div>
			</div>

			<div class="min-h-[8rem] flex-1 overflow-y-auto px-2">
				{#if loading}
					<div class="flex justify-center py-10"><Spinner /></div>
				{:else if chats.length === 0}
					<div class="py-10 text-center text-sm text-gray-400">{$i18n.t('No chats found')}</div>
				{:else}
					{#each sortedChats as chat (chat.id)}
						<button
							type="button"
							class="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition hover:bg-gray-50 dark:hover:bg-gray-850"
							on:click={() => toggle(chat.id)}
						>
							<input
								type="checkbox"
								checked={selected.has(chat.id)}
								class="pointer-events-none"
								tabindex="-1"
							/>
							<span class="flex-1 truncate text-sm text-gray-700 dark:text-gray-200">
								{chat.title || $i18n.t('New Chat')}
							</span>
							{#if chat.pinned}
								<span class="shrink-0 text-[10px] text-gray-400">{$i18n.t('Pinned')}</span>
							{/if}
						</button>
					{/each}
				{/if}
			</div>

			<div
				class="flex items-center justify-between gap-2 border-t border-gray-50 px-5 py-4 dark:border-gray-850"
			>
				<button
					type="button"
					class="rounded-xl px-3.5 py-2 text-sm text-gray-600 transition hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-850"
					on:click={() => (show = false)}
				>
					{$i18n.t('Cancel')}
				</button>
				<div class="flex items-center gap-2">
					<button
						type="button"
						class="flex items-center gap-1.5 rounded-xl bg-red-500/10 px-3.5 py-2 text-sm text-red-600 transition hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-40 dark:text-red-400"
						disabled={selected.size === 0 || deleting}
						on:click={deleteSelected}
					>
						{#if deleting}<Spinner className="size-3.5" />{/if}
						{$i18n.t('Delete selected ({{n}})', { n: selected.size })}
					</button>
					<button
						type="button"
						class="rounded-xl bg-black px-3.5 py-2 text-sm text-white transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40 dark:bg-white dark:text-black"
						disabled={overCap}
						title={overCap ? $i18n.t('Delete a chat to continue') : ''}
						on:click={startNewChat}
					>
						{$i18n.t('Start new chat')}
					</button>
				</div>
			</div>
		</div>
	</div>
{/if}
