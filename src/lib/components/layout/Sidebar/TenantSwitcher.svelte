<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import { tenants, activeTenant } from '$lib/stores';
	import { setActiveTenant } from '$lib/apis/tenant';
	import Dropdown from '$lib/components/common/Dropdown.svelte';

	const i18n = getContext<Writable<any>>('i18n');

	let show = false;

	// The active tenant's display label (name, falling back to slug).
	$: current = $tenants.find((t) => t.slug === $activeTenant) ?? $tenants[0];

	const switchTo = (slug: string) => {
		show = false;
		if (slug === $activeTenant) return;
		// Switching business unit means a different DB / Qdrant / bucket. A full
		// reload re-runs the layout gate: it re-selects the tenant, re-stamps
		// X-Tenant-Id, re-fetches the session under the new tenant, and
		// re-handshakes the socket — the safe way to swap the entire data plane.
		setActiveTenant(slug);
		activeTenant.set(slug);
		window.location.href = '/';
	};
</script>

{#if $tenants.length > 0 && current}
	<div class="px-[0.4375rem] flex justify-center text-gray-800 dark:text-gray-200">
		<Dropdown
			bind:show
			align="start"
			contentClass="w-64 rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 shadow-lg p-1 text-sm"
		>
			<button
				type="button"
				class="group grow flex items-center w-full space-x-2 rounded-2xl px-2.5 py-2 brand-nav-item transition outline-none"
				aria-label={$i18n.t('Switch workspace')}
				disabled={$tenants.length < 2}
			>
				<div class="self-center flex size-4.5 items-center justify-center">
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						class="size-4.5"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M3.75 21h16.5M4.5 3h15M5.25 3v18m13.5-18v18M9 6.75h1.5m-1.5 3h1.5m-1.5 3h1.5m3-6H15m-1.5 3H15m-1.5 3H15M9 21v-3.375c0-.621.504-1.125 1.125-1.125h3.75c.621 0 1.125.504 1.125 1.125V21"
						/>
					</svg>
				</div>

				<div class="flex flex-1 min-w-0 self-center translate-y-[0.5px]">
					<div class="self-center text-sm font-primary truncate">
						{current.name ?? current.slug}
					</div>
				</div>

				{#if $tenants.length > 1}
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="size-4 text-gray-400 shrink-0"
					>
						<path
							fill-rule="evenodd"
							d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z"
							clip-rule="evenodd"
						/>
					</svg>
				{/if}
			</button>

			<div slot="content">
				<div class="px-2 py-1.5 text-xs text-gray-400 dark:text-gray-500">
					{$i18n.t('Workspaces')}
				</div>
				{#each $tenants as t (t.slug)}
					<button
						type="button"
						class="flex items-center w-full gap-2 rounded-lg px-2 py-1.5 text-left brand-nav-item transition"
						on:click={() => switchTo(t.slug)}
					>
						<div class="flex-1 min-w-0">
							<div class="truncate text-gray-800 dark:text-gray-100">{t.name ?? t.slug}</div>
							<div class="truncate text-xs text-gray-400 dark:text-gray-500">
								{t.slug} · {t.role}
							</div>
						</div>
						{#if t.slug === $activeTenant}
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 20 20"
								fill="currentColor"
								class="size-4 text-gray-700 dark:text-gray-200 shrink-0"
							>
								<path
									fill-rule="evenodd"
									d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z"
									clip-rule="evenodd"
								/>
							</svg>
						{/if}
					</button>
				{/each}
			</div>
		</Dropdown>
	</div>
{/if}
