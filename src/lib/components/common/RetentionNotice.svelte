<script lang="ts">
	import { getContext } from 'svelte';
	import { config } from '$lib/stores';

	const i18n = getContext('i18n');

	// 'banner'  -> dismissible info bar (A, D: pass dismissible={false} for Settings)
	// 'counter' -> "X / N chats" pill (B); pass chatCount
	// 'badge'   -> "Expires in Nd" chip on a chat row (C); pass updatedAt (epoch seconds)
	export let variant: 'banner' | 'counter' | 'badge' = 'banner';
	export let chatCount = 0;
	export let updatedAt = 0;
	export let dismissible = true;
	/** badge only shows within this many days of expiry */
	export let badgeThresholdDays = 7;

	let dismissed = false;

	$: retentionDays = $config?.retention?.chat_retention_days ?? 0;
	$: maxChats = $config?.retention?.max_chats_per_user ?? 0;

	$: daysLeft =
		retentionDays > 0 && updatedAt
			? Math.ceil((updatedAt + retentionDays * 86400 - Date.now() / 1000) / 86400)
			: null;
</script>

{#if variant === 'banner'}
	{#if retentionDays > 0 && !(dismissible && dismissed)}
		<div
			class="flex items-center justify-between gap-2 px-3 py-2 text-xs rounded-lg bg-gray-50 dark:bg-gray-850 text-gray-600 dark:text-gray-400"
		>
			<span>
				{$i18n.t('Chats inactive for {{days}} days are removed automatically.', {
					days: retentionDays
				})}
				{#if maxChats > 0}
					{$i18n.t('Each user can keep up to {{max}} chats.', { max: maxChats })}
				{/if}
			</span>
			{#if dismissible}
				<button
					class="shrink-0 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
					on:click={() => (dismissed = true)}
					aria-label={$i18n.t('Dismiss')}
				>
					✕
				</button>
			{/if}
		</div>
	{/if}
{:else if variant === 'counter'}
	{#if maxChats > 0}
		<span
			class="text-xs px-1.5 py-0.5 rounded-full {chatCount >= maxChats
				? 'text-red-500'
				: 'text-gray-400'}"
			title={$i18n.t('Chats used out of your limit')}
		>
			{chatCount} / {maxChats}
		</span>
	{/if}
{:else if variant === 'badge'}
	{#if daysLeft !== null && daysLeft <= badgeThresholdDays}
		<span
			class="text-[10px] px-1 py-0.5 rounded {daysLeft <= 2
				? 'text-red-500'
				: 'text-gray-400'}"
			title={$i18n.t('This chat will be removed by the retention policy')}
		>
			{$i18n.t('Expires in {{n}}d', { n: Math.max(daysLeft, 0) })}
		</span>
	{/if}
{/if}
