<script lang="ts">
	import { marked } from 'marked';
	import Fuse from 'fuse.js';

	import dayjs from '$lib/dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import Spinner from '$lib/components/common/Spinner.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import { flyAndScale } from '$lib/utils/transitions';

	import { createEventDispatcher, onMount, getContext, tick } from 'svelte';
	import { goto } from '$app/navigation';

	import { unloadModel } from '$lib/apis';

	import { user, models, mobile, temporaryChatEnabled, settings, config } from '$lib/stores';
	import { toast } from 'svelte-sonner';
	import { capitalizeFirstLetter, sanitizeResponseContent, splitStream } from '$lib/utils';
	import { getModels } from '$lib/apis';

	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Check from '$lib/components/icons/Check.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import ChatBubbleOval from '$lib/components/icons/ChatBubbleOval.svelte';

	import ModelItem from './ModelItem.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let id = '';
	export let value = '';
	export let placeholder = $i18n.t('Select a model');
	export let searchEnabled = true;
	export let searchPlaceholder = $i18n.t('Search a model');

	export let items: {
		label: string;
		value: string;
		model: Model;
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		[key: string]: any;
	}[] = [];

	export let className = 'w-[32rem]';
	export let triggerClassName = 'text-lg';

	export let pinModelHandler: (modelId: string) => void = () => {};

	let tagsContainerElement;

	let show = false;
	let triggerElement: HTMLElement | null = null;
	let contentElement: HTMLElement | null = null;
	let dropdownPosition = { top: 0, left: 0, width: 0 };

	const portal = (node: HTMLElement) => {
		document.body.appendChild(node);
		return {
			destroy() {
				node.remove();
			}
		};
	};

	// Sunway: viewport-aware positioning. Upstream hard-set `left` to the trigger's left edge and
	// always opened downward, which was fine while the selector lived in the top-left navbar. Now
	// that it sits in the composer beside Send — near the right edge AND near the bottom — a
	// left-anchored, downward-only panel gets clipped by the window edge. This is not a zoom or
	// responsiveness bug: `on:resize` below already recomputes on zoom (browser zoom fires
	// resize); the maths simply had no overflow handling. Two passes are required because the
	// panel only exists once `show` renders it, so it cannot be measured on the first call.
	const updatePosition = async () => {
		if (!show || !triggerElement) return;
		const rect = triggerElement.getBoundingClientRect();

		if ($mobile) {
			dropdownPosition = { top: rect.bottom + 2, left: 8, width: window.innerWidth - 16 };
			return;
		}

		// Pass 1: anchor under the trigger so the panel renders and becomes measurable.
		dropdownPosition = { top: rect.bottom + 2, left: rect.left, width: 0 };

		await tick();
		if (!show || !contentElement) return;

		const MARGIN = 8;
		const { width: panelWidth, height: panelHeight } = contentElement.getBoundingClientRect();

		// Horizontal: keep it left-aligned to the trigger while it fits, otherwise right-align to
		// the trigger, then clamp so the panel can never leave the viewport.
		let left = rect.left;
		if (left + panelWidth > window.innerWidth - MARGIN) {
			left = Math.min(rect.right - panelWidth, window.innerWidth - MARGIN - panelWidth);
		}
		left = Math.max(MARGIN, left);

		// Vertical: flip above the trigger when there is no room below it.
		let top = rect.bottom + 2;
		if (top + panelHeight > window.innerHeight - MARGIN) {
			const above = rect.top - panelHeight - 2;
			top = above >= MARGIN ? above : Math.max(MARGIN, window.innerHeight - MARGIN - panelHeight);
		}

		dropdownPosition = { top, left, width: 0 };
	};

	const toggleOpen = () => {
		show = !show;
		if (show) {
			searchValue = '';
			listScrollTop = 0;
			resetView();
			updatePosition();
			window.setTimeout(() => document.getElementById('model-search-input')?.focus(), 0);
		} else {
			document.getElementById(`model-selector-${id}-button`)?.blur();
		}
	};

	const handlePointerDown = (e: PointerEvent) => {
		if (!show) return;
		const target = e.target as Node;
		if (
			(triggerElement && triggerElement.contains(target)) ||
			(contentElement && contentElement.contains(target))
		) {
			return;
		}
		show = false;
		document.getElementById(`model-selector-${id}-button`)?.blur();
	};

	const handleKeydown = (e: KeyboardEvent) => {
		if (show && e.key === 'Escape') {
			e.preventDefault();
			e.stopPropagation();
			show = false;
			document.getElementById(`model-selector-${id}-button`)?.blur();
		}
	};

	let tags = [];

	let selectedModel = '';
	$: selectedModel = items.find((item) => item.value === value) ?? '';

	let searchValue = '';

	let selectedTag = '';
	let selectedConnectionType = '';

	let selectedModelIdx = 0;

	const fuse = new Fuse(
		items.map((item) => {
			const _item = {
				...item,
				modelName: item.model?.name,
				tags: (item.model?.tags ?? []).map((tag) => tag.name).join(' '),
				desc: item.model?.info?.meta?.description
			};
			return _item;
		}),
		{
			keys: ['value', 'tags', 'modelName'],
			threshold: 0.4
		}
	);

	const updateFuse = () => {
		if (fuse) {
			fuse.setCollection(
				items.map((item) => {
					const _item = {
						...item,
						modelName: item.model?.name,
						tags: (item.model?.tags ?? []).map((tag) => tag.name).join(' '),
						desc: item.model?.info?.meta?.description
					};
					return _item;
				})
			);
		}
	};

	$: if (items) {
		updateFuse();
	}

	$: filteredItems = (
		searchValue
			? fuse
					.search(searchValue)
					.map((e) => {
						return e.item;
					})
					.filter((item) => {
						if (selectedTag === '') {
							return true;
						}

						return (item.model?.tags ?? [])
							.map((tag) => tag.name.toLowerCase())
							.includes(selectedTag.toLowerCase());
					})
					.filter((item) => {
						if (selectedConnectionType === '') {
							return true;
						} else if (selectedConnectionType === 'local') {
							return item.model?.connection_type === 'local';
						} else if (selectedConnectionType === 'external') {
							return item.model?.connection_type === 'external';
						} else if (selectedConnectionType === 'direct') {
							return item.model?.direct;
						}
					})
			: items
					.filter((item) => {
						if (selectedTag === '') {
							return true;
						}
						return (item.model?.tags ?? [])
							.map((tag) => tag.name.toLowerCase())
							.includes(selectedTag.toLowerCase());
					})
					.filter((item) => {
						if (selectedConnectionType === '') {
							return true;
						} else if (selectedConnectionType === 'local') {
							return item.model?.connection_type === 'local';
						} else if (selectedConnectionType === 'external') {
							return item.model?.connection_type === 'external';
						} else if (selectedConnectionType === 'direct') {
							return item.model?.direct;
						}
					})
	).filter((item) => !(item.model?.info?.meta?.hidden ?? false));

	$: if (
		selectedTag !== undefined ||
		selectedConnectionType !== undefined ||
		searchValue !== undefined
	) {
		resetView();
	}

	const resetView = async () => {
		await tick();

		const selectedInFiltered = filteredItems.findIndex((item) => item.value === value);

		if (selectedInFiltered >= 0) {
			// The selected model is visible in the current filter
			selectedModelIdx = selectedInFiltered;
		} else {
			// The selected model is not visible, default to first item in filtered list
			selectedModelIdx = 0;
		}

		// Set the virtual scroll position so the selected item is rendered and centered
		const targetScrollTop = Math.max(0, selectedModelIdx * ITEM_HEIGHT - 128 + ITEM_HEIGHT / 2);
		listScrollTop = targetScrollTop;

		await tick();

		if (listContainer) {
			listContainer.scrollTop = targetScrollTop;
		}

		await tick();
		const item = document.querySelector(`[data-arrow-selected="true"]`);
		item?.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
	};

	onMount(async () => {
		if (items) {
			tags = items
				.filter((item) => !(item.model?.info?.meta?.hidden ?? false))
				.flatMap((item) => item.model?.tags ?? [])
				.map((tag) => tag.name.toLowerCase());
			// Remove duplicates and sort
			tags = Array.from(new Set(tags)).sort((a, b) => a.localeCompare(b));
		}
	});

	const unloadModelHandler = async (model: string) => {
		const res = await unloadModel(localStorage.token, model).catch((error) => {
			toast.error($i18n.t('Error unloading model: {{error}}', { error }));
		});

		if (res) {
			toast.success($i18n.t('Model unloaded successfully'));
			models.set(
				await getModels(
					localStorage.token,
					$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
				)
			);
		}
	};

	// Sunway: pullModelHandler, deleteModelHandler and the Ollama version probe were removed
	// here (hardening plan Item 6). They drove /ollama/api/pull, /api/delete and /api/version.
	// The Delete entry in ModelItemMenu is gated on `owned_by === 'ollama'`, which no model can
	// be, so it renders for nobody and needs no handler.

	const ITEM_HEIGHT = 42;
	const OVERSCAN = 10;

	let listScrollTop = 0;
	let listContainer;

	$: visibleStart = Math.max(0, Math.floor(listScrollTop / ITEM_HEIGHT) - OVERSCAN);
	$: visibleEnd = Math.min(
		filteredItems.length,
		Math.ceil((listScrollTop + 256) / ITEM_HEIGHT) + OVERSCAN
	);
</script>

<svelte:window
	on:pointerdown={handlePointerDown}
	on:keydown={handleKeydown}
	on:resize={updatePosition}
/>

<div class="relative w-full">
	<button
		bind:this={triggerElement}
		class="relative w-full {($settings?.highContrastMode ?? false)
			? ''
			: 'outline-hidden focus:outline-hidden'}"
		aria-label={selectedModel
			? $i18n.t('Selected model: {{modelName}}', { modelName: selectedModel.label })
			: placeholder}
		aria-haspopup="listbox"
		aria-expanded={show}
		id="model-selector-{id}-button"
		type="button"
		on:click={toggleOpen}
	>
		<div
			class="brand-pill-outline w-full text-gray-600 dark:text-gray-300 text-left truncate {triggerClassName} justify-between {($settings?.highContrastMode ??
			false)
				? 'dark:placeholder-gray-100 placeholder-gray-800'
				: 'placeholder-gray-400'}"
			on:mouseenter={async () => {
				models.set(
					await getModels(
						localStorage.token,
						$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
					)
				);
			}}
		>
			{#if selectedModel}
				{selectedModel.label}
			{:else}
				{placeholder}
			{/if}
			<ChevronDown className=" self-center size-3" strokeWidth="2.5" />
		</div>
	</button>

	{#if show}
		<div
			use:portal
			bind:this={contentElement}
			style="position: fixed; z-index: 9999; top: {dropdownPosition.top}px; left: {dropdownPosition.left}px;{$mobile
				? ` width: ${dropdownPosition.width}px;`
				: ''}"
		>
			<!-- Sunway: py-1 added. Upstream relied on the search block's own `pt-3.5 mb-1.5`
			     (below) for the panel's top inset, so with searchEnabled={false} and the filter
			     chips hidden the item list sat flush against the rounded top edge and the first
			     row's hover highlight bled into it. py-1 puts the inset on the CONTAINER instead,
			     so it holds regardless of which optional children are shown — and it matches the
			     px-1 py-1 used by the other dropdown panels in this codebase. -->
			<div
				class="z-40 {$mobile
					? `w-full`
					: `${className}`} max-w-[calc(100vw-1rem)] justify-start rounded-2xl bg-white dark:bg-gray-850 dark:text-white shadow-lg outline-hidden py-1"
				transition:flyAndScale
			>
				<slot>
					{#if searchEnabled}
						<div class="flex items-center gap-2.5 px-4.5 pt-3.5 mb-1.5">
							<Search className="size-4" strokeWidth="2.5" />

							<input
								id="model-search-input"
								bind:value={searchValue}
								class="w-full text-sm bg-transparent outline-hidden"
								placeholder={searchPlaceholder}
								autocomplete="off"
								aria-label={$i18n.t('Search In Models')}
								on:keydown={(e) => {
									if (e.code === 'Enter' && filteredItems.length > 0) {
										value = filteredItems[selectedModelIdx].value;
										show = false;
										return; // dont need to scroll on selection
									} else if (e.code === 'ArrowDown') {
										e.stopPropagation();
										selectedModelIdx = Math.min(selectedModelIdx + 1, filteredItems.length - 1);
									} else if (e.code === 'ArrowUp') {
										e.stopPropagation();
										selectedModelIdx = Math.max(selectedModelIdx - 1, 0);
									} else {
										// if the user types something, reset to the top selection.
										selectedModelIdx = 0;
									}

									const item = document.querySelector(`[data-arrow-selected="true"]`);
									item?.scrollIntoView({
										block: 'center',
										inline: 'nearest',
										behavior: 'instant'
									});
								}}
							/>
						</div>
					{/if}

					<div class="px-2">
						<!-- Sunway: connection-type / tag filter chips hidden. The picker lists exactly
					     three curated tiers, so "All | Local | External | Direct" filters nothing
					     useful. Worth knowing WHY "External" showed at all with only three items
					     visible: the chips below test the UNFILTERED `items`, while the row's own
					     guard and the list both exclude meta.hidden — so the five hidden base
					     models still contributed chips they could never filter to. `tags` is a
					     local computed value, not a prop, so this is a {#if false} guard rather
					     than a prop from ModelSelector; the whole block is left intact for clean
					     upstream syncs. Original guard:
					     {#if tags && items.filter((item) => !(item.model?.info?.meta?.hidden ?? false)).length > 0} -->
						{#if false}
							<div
								class=" flex w-full bg-white dark:bg-gray-850 overflow-x-auto scrollbar-none font-[450] mb-0.5"
								on:wheel={(e) => {
									if (e.deltaY !== 0) {
										e.preventDefault();
										e.currentTarget.scrollLeft += e.deltaY;
									}
								}}
							>
								<div
									class="flex gap-1 w-fit text-center text-sm rounded-full bg-transparent px-1.5 whitespace-nowrap"
									bind:this={tagsContainerElement}
								>
									{#if items.find((item) => item.model?.connection_type === 'local') || items.find((item) => item.model?.connection_type === 'external') || items.find((item) => item.model?.direct) || tags.length > 0}
										<button
											class="min-w-fit outline-none px-1.5 py-0.5 {selectedTag === '' &&
											selectedConnectionType === ''
												? ''
												: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition capitalize"
											aria-pressed={selectedTag === '' && selectedConnectionType === ''}
											on:click={() => {
												selectedConnectionType = '';
												selectedTag = '';
											}}
										>
											{$i18n.t('All')}
										</button>
									{/if}

									{#if items.find((item) => item.model?.connection_type === 'local')}
										<button
											class="min-w-fit outline-none px-1.5 py-0.5 {selectedConnectionType ===
											'local'
												? ''
												: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition capitalize"
											aria-pressed={selectedConnectionType === 'local'}
											on:click={() => {
												selectedTag = '';
												selectedConnectionType = 'local';
											}}
										>
											{$i18n.t('Local')}
										</button>
									{/if}

									{#if items.find((item) => item.model?.connection_type === 'external')}
										<button
											class="min-w-fit outline-none px-1.5 py-0.5 {selectedConnectionType ===
											'external'
												? ''
												: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition capitalize"
											aria-pressed={selectedConnectionType === 'external'}
											on:click={() => {
												selectedTag = '';
												selectedConnectionType = 'external';
											}}
										>
											{$i18n.t('External')}
										</button>
									{/if}

									{#if items.find((item) => item.model?.direct)}
										<button
											class="min-w-fit outline-none px-1.5 py-0.5 {selectedConnectionType ===
											'direct'
												? ''
												: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition capitalize"
											aria-pressed={selectedConnectionType === 'direct'}
											on:click={() => {
												selectedTag = '';
												selectedConnectionType = 'direct';
											}}
										>
											{$i18n.t('Direct')}
										</button>
									{/if}

									{#each tags as tag}
										<Tooltip content={tag}>
											<button
												class="min-w-fit outline-none px-1.5 py-0.5 {selectedTag === tag
													? ''
													: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition capitalize"
												aria-pressed={selectedTag === tag}
												on:click={() => {
													selectedConnectionType = '';
													selectedTag = tag;
												}}
											>
												{tag.length > 16 ? `${tag.slice(0, 16)}...` : tag}
											</button>
										</Tooltip>
									{/each}
								</div>
							</div>
						{/if}
					</div>

					<div class="px-2.5 group relative">
						{#if filteredItems.length === 0}
							{#if items.length === 0 && $user?.role === 'admin'}
								<div class="flex flex-col items-start justify-center py-6 px-4 text-start">
									<div class="text-sm font-medium text-gray-900 dark:text-gray-100 mb-1">
										{$i18n.t('No models available')}
									</div>
									<div class="text-xs text-gray-500 dark:text-gray-400 mb-4">
										{$i18n.t('Connect to an AI provider to start chatting')}
									</div>
									<!-- Sunway: the "Manage Connections" link was deleted here (hardening plan Item 7).
									     Admin Settings -> Connections is gone; provider connections come from the
									     chart. An empty model list is now an infrastructure problem, not something
									     a user or a BU admin can fix from this dropdown. -->
								</div>
							{:else}
								<div class="">
									<div class="block px-3 py-2 text-sm text-gray-700 dark:text-gray-100">
										{$i18n.t('No results found')}
									</div>
								</div>
							{/if}
						{:else}
							<!-- svelte-ignore a11y-no-static-element-interactions -->
							<div
								class="max-h-64 overflow-y-auto"
								role="listbox"
								aria-label={$i18n.t('Available models')}
								bind:this={listContainer}
								on:scroll={() => {
									listScrollTop = listContainer.scrollTop;
								}}
							>
								<div style="height: {visibleStart * ITEM_HEIGHT}px;" />
								{#each filteredItems.slice(visibleStart, visibleEnd) as item, i (item.value)}
									{@const index = visibleStart + i}
									<ModelItem
										{selectedModelIdx}
										{item}
										{index}
										{value}
										{pinModelHandler}
										{unloadModelHandler}
										onClick={() => {
											value = item.value;
											selectedModelIdx = index;

											show = false;
										}}
									/>
								{/each}
								<div style="height: {(filteredItems.length - visibleEnd) * ITEM_HEIGHT}px;" />
							</div>
						{/if}

						<!-- Sunway: the "Pull from Ollama.com" action and the download-progress list were
						     deleted here (hardening plan Item 6). Both drove /ollama/api/pull, which is
						     gone; Ollama is out of scope. -->
					</div>

					<div class="pb-2.5"></div>

					<div class="hidden w-[42rem]" />
					<div class="hidden w-[32rem]" />
				</slot>
			</div>
		</div>
	{/if}
</div>
