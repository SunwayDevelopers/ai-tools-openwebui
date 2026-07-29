<script lang="ts">
	import { getContext } from 'svelte';
	import { config } from '$lib/stores';
	import { getDaysUntilExpiry } from '$lib/utils/retention';

	const i18n = getContext('i18n');

	// 'banner'  -> dismissible info bar (A, D: pass dismissible={false} for Settings)
	// 'counter' -> "X / N chats" pill (B); pass chatCount
	// 'badge'   -> "Expires in Nd" chip on a chat row (C); pass updatedAt (epoch seconds)
	export let variant: 'banner' | 'counter' | 'badge' = 'banner';
	export let chatCount = 0;
	export let updatedAt: number | null = 0;
	export let dismissible = true;
	/** badge only shows within this many days of expiry */
	export let badgeThresholdDays = 7;

	$: retentionDays = $config?.retention?.chat_retention_days ?? 0;
	$: maxChats = $config?.retention?.max_chats_per_user ?? 0;

	// Sunway: the dismissal has to persist. Previously this was plain component state, so the ✕
	// only held until the next remount — users dismissed it, reloaded, and saw it again forever,
	// which reads as "this control is broken" rather than "this notice is important".
	//
	// The key embeds the policy values, so changing CHAT_RETENTION_DAYS or MAX_CHATS_PER_USER
	// re-surfaces the banner for everyone. That's intentional: a policy change is exactly when
	// people need to be re-told, and a permanently dismissed banner would hide it. Dismissing
	// costs nothing in awareness terms — the counter pill and the per-row expiry badge remain.
	$: dismissKey = `schat:retention-notice-dismissed:${retentionDays}:${maxChats}`;

	let dismissed = false;
	$: {
		try {
			dismissed = localStorage.getItem(dismissKey) === 'true';
		} catch {
			// Storage unavailable (private mode) — banner simply stays dismissible per-session.
			dismissed = false;
		}
	}

	const dismiss = () => {
		dismissed = true;
		try {
			localStorage.setItem(dismissKey, 'true');
		} catch {
			// Non-fatal: we lose persistence, not the dismissal itself.
		}
	};

	$: daysLeft = getDaysUntilExpiry(updatedAt, retentionDays);
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
					on:click={dismiss}
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
			class="text-[10px] px-1 py-0.5 rounded {daysLeft <= 2 ? 'text-red-500' : 'text-gray-400'}"
			title={$i18n.t('This chat will be removed by the retention policy')}
		>
			{$i18n.t('Expires in {{n}}d', { n: Math.max(daysLeft, 0) })}
		</span>
	{/if}
{/if}
