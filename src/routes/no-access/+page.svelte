<script lang="ts">
	import { WEBUI_NAME, config } from '$lib/stores';
	import { endSession } from '$lib/utils/session';

	// Shown when a valid login has NO active business-unit membership. Per the IAM
	// contract (§5.5) a successful sign-in does not imply access — the user must be
	// added to a workspace by an admin. We block here rather than fall through to a
	// default workspace (fail-closed).

	let signingOut = false;
	let signOutError: string | null = null;

	// Sign-out ordering, and the tenant-middleware bypass this depends on, are both
	// documented in endSession(). A failure is reported rather than swallowed: the
	// old `.catch(() => {})` hid a guaranteed 400 and left the user with no way off
	// this page short of clearing cookies by hand (todo.md T1.4).
	const signOut = async () => {
		signingOut = true;
		signOutError = null;
		try {
			window.location.href = await endSession();
		} catch (err) {
			signOutError = (err as any)?.detail ?? (err as Error)?.message ?? `${err}`;
			signingOut = false;
		}
	};
</script>

<svelte:head>
	<title>No workspace access • {$WEBUI_NAME}</title>
</svelte:head>

<div class="flex min-h-screen w-full items-center justify-center bg-white px-6 dark:bg-gray-900">
	<div class="max-w-md text-center">
		<div class="mb-5 flex justify-center">
			<div
				class="flex h-14 w-14 items-center justify-center rounded-full bg-gray-100 dark:bg-gray-800"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="1.5"
					stroke="currentColor"
					class="h-7 w-7 text-gray-500 dark:text-gray-400"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z"
					/>
				</svg>
			</div>
		</div>

		<h1 class="text-xl font-semibold text-gray-800 dark:text-gray-100">
			You don't have access to any workspace yet
		</h1>
		<p class="mt-2 text-sm text-gray-500 dark:text-gray-400">
			Your sign-in was successful, but your account hasn't been added to a workspace. Please contact
			your administrator to request access, then sign in again.
		</p>

		<div class="mt-6 flex items-center justify-center gap-3">
			<button
				class="rounded-full bg-gray-900 px-4 py-2 text-sm font-medium text-white transition brand-nav-item disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900 brand-nav-item"
				on:click={signOut}
				disabled={signingOut}
			>
				{signingOut ? 'Signing out…' : 'Sign out'}
			</button>

			<!-- Deliberately a link, not a redirect. The visitor holds a VALID session here —
			     they are authenticated but hold no membership — so bouncing them to the
			     catalogue would only send them back, and signing in again cannot help. Only
			     an admin granting access can. -->
			{#if $config?.features?.landing_page_url}
				<a
					class="rounded-full border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition brand-nav-item dark:border-gray-700 dark:text-gray-200 brand-nav-item"
					href={$config.features.landing_page_url}
				>
					Back to catalogue
				</a>
			{/if}
		</div>

		{#if signOutError}
			<p class="mt-4 text-xs text-red-600 dark:text-red-400">
				Sign-out failed ({signOutError}). Your session may still be active — close the browser or
				clear cookies for this site.
			</p>
		{/if}
	</div>
</div>
