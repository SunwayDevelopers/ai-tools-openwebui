<script lang="ts">
	import { getContext, createEventDispatcher } from 'svelte';
	const dispatch = createEventDispatcher();

	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import ArrowUpCircle from '$lib/components/icons/ArrowUpCircle.svelte';
	import BarsArrowUp from '$lib/components/icons/BarsArrowUp.svelte';
	import FolderOpen from '$lib/components/icons/FolderOpen.svelte';
	import NewFolderAlt from '$lib/components/icons/NewFolderAlt.svelte';
	import ArrowPath from '$lib/components/icons/ArrowPath.svelte';
	import GlobeAlt from '$lib/components/icons/GlobeAlt.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import ArrowUturnLeft from '$lib/components/icons/ArrowUturnLeft.svelte';
	import EllipsisHorizontal from '$lib/components/icons/EllipsisHorizontal.svelte';

	const i18n = getContext('i18n');

	export let onClose: Function = () => {};

	export let onSync: Function = () => {};
	export let onUpload: Function = (data) => {};
	export let onReset: Function = () => {};

	let show = false;
</script>

<!-- Sunway: the "+" dropdown is split. Uploading is the whole point of this screen, so it is
     a primary pill in the header rather than one of two entries hidden behind a plus icon.
     Reset is deliberately NOT promoted beside it: it deletes every file and vector in the
     collection with no undo, and giving a destructive action equal weight next to the button
     people click constantly is a mis-click waiting to happen. It lives in an overflow menu,
     styled as destructive. The hidden directory / webpage / text entries stay in that menu. -->
<div class="flex items-center gap-1.5">
	<button
		class="brand-pill-solid"
		on:click={(e) => {
			e.stopPropagation();
			onUpload({ type: 'files' });
		}}
	>
		<ArrowUpCircle strokeWidth="2.5" className="size-3.5 shrink-0" />
		<span class="hidden md:inline">{$i18n.t('Upload files')}</span>
	</button>

	<Dropdown
		bind:show
		onOpenChange={(state) => {
			if (state === false) {
				onClose();
			}
		}}
		align="end"
	>
		<Tooltip content={$i18n.t('More')}>
			<button
				class="brand-nav-item p-1.5 rounded-xl transition flex items-center"
				aria-label={$i18n.t('More')}
				on:click={(e) => {
					e.stopPropagation();
					show = true;
				}}
			>
				<EllipsisHorizontal className="size-4" />
			</button>
		</Tooltip>

		<div slot="content">
			<div
				class="min-w-[200px] rounded-2xl px-1 py-1 border border-gray-100 dark:border-gray-800 z-50 bg-white dark:bg-gray-850 dark:text-white shadow-lg transition"
			>
				<!-- Sunway: Knowledge content actions narrowed to "Upload files" + "Reset" for the
			     rollout. Directory-based ingestion (New / Upload / Sync directory) pulls whole
			     folder trees from a user's machine into a shared KB, which makes accidental bulk
			     disclosure a single click. "Add webpage" is the KB-side twin of the Attach Webpage
			     entry already hidden in MessageInput/InputMenu (see CLAUDE.md), and "Add text
			     content" pastes unattributed free text into a governed collection.
			     The `<hr>` below is hidden with this first entry rather than left behind, or the
			     menu would open with a stray divider above "Upload files". All handlers and modals
			     (showNewDirectoryModal / showAddWebpageModal / showAddTextContentModal, onSync) are
			     left intact and simply unreachable, for clean upstream syncs. -->
				{#if false}
					<button
						class="select-none flex gap-2 items-center px-3 py-1.5 text-sm cursor-pointer brand-nav-item rounded-xl w-full"
						on:click={() => {
							onUpload({ type: 'new_directory' });
							show = false;
						}}
					>
						<NewFolderAlt />
						<div class="flex items-center">{$i18n.t('New directory')}</div>
					</button>

					<hr class="my-1 border-gray-100 dark:border-gray-800" />
				{/if}

				<!-- Sunway: Upload directory / Sync directory / Add webpage / Add text content hidden.
			     See the rationale on the "New directory" guard above. -->
				{#if false}
					<button
						class="select-none flex gap-2 items-center px-3 py-1.5 text-sm cursor-pointer brand-nav-item rounded-xl w-full"
						on:click={() => {
							onUpload({ type: 'directory' });
						}}
					>
						<FolderOpen strokeWidth="2" />
						<div class="flex items-center">{$i18n.t('Upload directory')}</div>
					</button>

					<Tooltip
						content={$i18n.t(
							'Sync a local directory with this knowledge base. Only new and modified files will be uploaded. The directory structure will be mirrored.'
						)}
						className="w-full"
					>
						<button
							class="select-none flex gap-2 items-center px-3 py-1.5 text-sm cursor-pointer brand-nav-item rounded-xl w-full"
							on:click={() => {
								onSync();
							}}
						>
							<ArrowPath strokeWidth="2" />
							<div class="flex items-center">{$i18n.t('Sync directory')}</div>
						</button>
					</Tooltip>

					<button
						class="select-none flex gap-2 items-center px-3 py-1.5 text-sm cursor-pointer brand-nav-item rounded-xl w-full"
						on:click={() => {
							onUpload({ type: 'web' });
						}}
					>
						<GlobeAlt strokeWidth="2" />
						<div class="flex items-center">{$i18n.t('Add webpage')}</div>
					</button>

					<button
						class="select-none flex gap-2 items-center px-3 py-1.5 text-sm cursor-pointer brand-nav-item rounded-xl w-full"
						on:click={() => {
							onUpload({ type: 'text' });
						}}
					>
						<BarsArrowUp strokeWidth="2" />
						<div class="flex items-center">{$i18n.t('Add text content')}</div>
					</button>
				{/if}

				<button
					class="select-none flex gap-2 items-center px-3 py-1.5 text-sm cursor-pointer rounded-xl w-full text-red-600 dark:text-red-400 hover:bg-red-500/10 transition"
					on:click={() => {
						onReset();
						show = false;
					}}
				>
					<ArrowUturnLeft strokeWidth="2" />
					<div class="flex items-center">{$i18n.t('Reset')}</div>
				</button>
			</div>
		</div>
	</Dropdown>
</div>
