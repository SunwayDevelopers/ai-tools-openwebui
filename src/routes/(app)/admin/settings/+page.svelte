<script>
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import Settings from '$lib/components/admin/Settings.svelte';
	import { DEFAULT_ADMIN_SETTINGS_TAB } from '$lib/utils/admin-settings-tabs';

	onMount(() => {
		// Sunway: was a hard-coded '/admin/settings/general'. General is now hidden, so this
		// lands on whichever tab is first-visible rather than one that no longer renders.
		goto(`/admin/settings/${DEFAULT_ADMIN_SETTINGS_TAB}`);
	});
</script>

<Settings />
