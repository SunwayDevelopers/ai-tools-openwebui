<script lang="ts">
	import { WEBUI_BASE_URL } from '$lib/constants';
	import { safeImageUrl } from '$lib/utils/safeImageUrl';
	import { copyImageToClipboard } from '$lib/utils';

	import { settings } from '$lib/stores';
	import ImagePreview from './ImagePreview.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Clipboard from '$lib/components/icons/Clipboard.svelte';
	import Check from '$lib/components/icons/Check.svelte';
	import Tooltip from './Tooltip.svelte';
	import { getContext, onDestroy } from 'svelte';
	import { toast } from 'svelte-sonner';

	export let src = '';
	export let alt = '';

	export let className = ` w-full ${($settings?.highContrastMode ?? false) ? '' : 'outline-hidden focus:outline-hidden'}`;

	export let imageClassName = 'rounded-lg';

	export let dismissible = false;
	export let onDismiss = () => {};

	// Sunway: opt-in per-image "Copy image" affordance. The response Copy button can only
	// carry text, so generated images need their own way out of the app.
	export let copyable = false;

	const i18n = getContext('i18n');

	let _src = '';
	$: _src = safeImageUrl(src.startsWith('/') ? `${WEBUI_BASE_URL}${src}` : src);

	let showImagePreview = false;

	let copied = false;
	let copiedTimer: ReturnType<typeof setTimeout>;

	const copyImageHandler = async () => {
		if (await copyImageToClipboard(_src)) {
			copied = true;
			clearTimeout(copiedTimer);
			copiedTimer = setTimeout(() => (copied = false), 1500);
		} else {
			toast.error($i18n.t('Could not copy image to clipboard'));
		}
	};

	onDestroy(() => clearTimeout(copiedTimer));
</script>

<ImagePreview bind:show={showImagePreview} src={_src} {alt} />

<div class=" relative group w-fit flex items-center">
	<button
		class={className}
		on:click={() => {
			showImagePreview = true;
		}}
		aria-label={$i18n.t('Show image preview')}
		type="button"
	>
		<img src={_src} {alt} class={imageClassName} draggable="false" data-cy="image" />
	</button>

	{#if copyable}
		<div class="absolute top-1.5 right-1.5">
			<Tooltip content={copied ? $i18n.t('Copied') : $i18n.t('Copy image')} placement="left">
				<button
					aria-label={$i18n.t('Copy image')}
					class="{copied
						? 'visible'
						: 'invisible group-hover:visible focus-visible:visible'} p-1.5 rounded-lg bg-white/90 dark:bg-gray-850/90 text-gray-700 dark:text-gray-200 hover:text-black dark:hover:text-white shadow-xs backdrop-blur-xs transition"
					type="button"
					on:click|stopPropagation={copyImageHandler}
				>
					{#if copied}
						<Check className="size-4" strokeWidth="2.5" />
					{:else}
						<Clipboard className="size-4" strokeWidth="2" />
					{/if}
				</button>
			</Tooltip>
		</div>
	{/if}

	{#if dismissible}
		<div class=" absolute -top-1 -right-1">
			<button
				aria-label={$i18n.t('Remove image')}
				class=" bg-white text-black border border-white rounded-full group-hover:visible invisible transition"
				type="button"
				on:click={() => {
					onDismiss();
				}}
			>
				<XMark className={'size-4'} />
			</button>
		</div>
	{/if}
</div>
