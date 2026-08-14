<script lang="ts">
	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import { onMount, getContext } from 'svelte';
	import { config, user } from '$lib/stores';
	import { getAllUsers } from '$lib/apis/users';

	const i18n = getContext('i18n');

	export let saveHandler: Function;

	const exportUsers = async () => {
		const users = await getAllUsers(localStorage.token);

		const headers = ['id', 'name', 'email', 'role'];

		const csv = [
			headers.join(','),
			...users.users.map((user) => {
				return headers
					.map((header) => {
						if (user[header] === null || user[header] === undefined) {
							return '';
						}
						return `"${String(user[header]).replace(/"/g, '""')}"`;
					})
					.join(',');
			})
		].join('\n');

		const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
		saveAs(blob, 'users.csv');
	};

	onMount(async () => {
		// permissions = await getUserPermissions(localStorage.token);
	});
</script>

<div class="flex flex-col h-full justify-between text-sm">
	<div class="space-y-3 overflow-y-scroll scrollbar-hidden h-full">
		<!-- Sunway: the Config section (Import Config / Export Config) was deleted here
		     (hardening plan Item 7). Both endpoints returned the entire config row unmasked --
		     every stored credential in one response -- and import was a process-global config
		     WRITE from a browser file-picker. Configuration belongs in the ConfigMap. -->

		{#if $config?.features.enable_admin_export ?? true}
			<div>
				<div class="mb-1 text-sm font-medium">{$i18n.t('Database')}</div>

				<!-- Sunway: "Download Database" was deleted here (hardening plan Item 3);
				     GET /api/v1/utils/db/download no longer exists. -->

				<!-- Sunway: "Export All Chats (All Users)" was deleted here (hardening plan Item 3);
				     GET /api/v1/chats/all/db returned every message of every user in one response. -->

				<div>
					<div class="py-0.5 flex w-full justify-between">
						<div class="self-center text-xs">{$i18n.t('Export Users')}</div>
						<button
							class="p-1 px-3 text-xs flex rounded-sm transition"
							on:click={() => {
								exportUsers();
							}}
							type="button"
						>
							<span class="self-center">{$i18n.t('Export')}</span>
						</button>
					</div>
				</div>
			</div>
		{/if}
	</div>
</div>
