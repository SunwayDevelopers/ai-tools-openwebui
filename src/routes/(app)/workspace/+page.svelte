<script lang="ts">
	import { goto } from '$app/navigation';
	import { user } from '$lib/stores';
	import { onMount } from 'svelte';

	import {
		DEFAULT_WORKSPACE_SECTION,
		VISIBLE_WORKSPACE_SECTIONS
	} from '$lib/utils/workspace-sections';

	// Sunway: this used to send admins straight to '/workspace/models', and non-admins to the
	// first section their permissions allowed — both hard-coded, both starting at Models. With
	// Models/Tools/Skills/Prompts hidden that landed the user IN a hidden section, because the
	// layout's route guard was onMount-only and does not re-run on a client-side navigation
	// within the same layout (the layout is already mounted at /workspace). Result: clicking
	// Workspace rendered the Models page even though its nav entry and guard both "hide" it.
	// Now this only ever targets a section that is actually visible.
	onMount(() => {
		if (!DEFAULT_WORKSPACE_SECTION) {
			goto('/');
			return;
		}

		if ($user?.role === 'admin') {
			goto(`/workspace/${DEFAULT_WORKSPACE_SECTION}`);
			return;
		}

		const permitted = VISIBLE_WORKSPACE_SECTIONS.find(
			(section) => $user?.permissions?.workspace?.[section]
		);

		goto(permitted ? `/workspace/${permitted}` : '/');
	});
</script>
