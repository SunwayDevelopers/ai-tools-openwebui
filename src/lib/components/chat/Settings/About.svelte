<script lang="ts">
	import { getVersionUpdates } from '$lib/apis';
	import { getOllamaVersion } from '$lib/apis/ollama';
	import { WEBUI_BUILD_HASH, WEBUI_VERSION, SCHAT_VERSION } from '$lib/constants';
	import { WEBUI_NAME, config, showChangelog } from '$lib/stores';
	import { compareVersion } from '$lib/utils';
	import { onMount, getContext } from 'svelte';

	import Tooltip from '$lib/components/common/Tooltip.svelte';

	const i18n = getContext('i18n');

	let ollamaVersion = '';

	let updateAvailable = null;
	let version = {
		current: '',
		latest: ''
	};

	const checkForVersionUpdates = async () => {
		updateAvailable = null;
		version = await getVersionUpdates(localStorage.token).catch((error) => {
			return {
				current: WEBUI_VERSION,
				latest: WEBUI_VERSION
			};
		});

		console.log(version);

		updateAvailable = compareVersion(version.latest, version.current);
		console.log(updateAvailable);
	};

	onMount(async () => {
		ollamaVersion = await getOllamaVersion(localStorage.token).catch((error) => {
			return '';
		});

		if ($config?.features?.enable_version_update_check) {
			checkForVersionUpdates();
		}
	});
</script>

<div id="tab-about" class="flex flex-col h-full justify-between space-y-3 text-sm mb-6">
	<div class=" space-y-3 overflow-y-scroll max-h-[28rem] md:max-h-full">
		<div>
			<div class=" mb-2.5 text-sm font-medium flex space-x-2 items-center">
				<div>
					{$WEBUI_NAME}
					{$i18n.t('Version')}
				</div>
			</div>
			<div class="flex w-full justify-between items-center">
				<div class="flex flex-col text-xs text-gray-700 dark:text-gray-200">
					<div class="flex gap-1">
						<Tooltip content={WEBUI_BUILD_HASH}>
							v{SCHAT_VERSION}
						</Tooltip>

						{#if $config?.features?.enable_version_update_check}
							<a
								href="https://github.com/open-webui/open-webui/releases/tag/v{version.latest}"
								target="_blank"
							>
								{updateAvailable === null
									? $i18n.t('Checking for updates...')
									: updateAvailable
										? `(v${version.latest} ${$i18n.t('available!')})`
										: $i18n.t('(latest)')}
							</a>
						{/if}
					</div>

					<!-- Sunway: Open WebUI attribution retained per licence (AUDIT-032); doubles as
					     our upstream-sync baseline (WEBUI_VERSION = the forked Open WebUI version). -->
					<div class="mt-0.5 text-gray-500 dark:text-gray-500">
						Powered by <a href="https://openwebui.com" target="_blank" class="underline"
							>Open WebUI</a
						>
						v{WEBUI_VERSION}
					</div>

					<!-- Sunway: "See what's new" opens Open WebUI's upstream CHANGELOG, which lists
					     upstream feature work that has no relationship to a schat release and is
					     confusing for staff. Not licence-bearing (the attribution line above is).
					     Hidden, not deleted. -->
					{#if false}
						<button
							class=" underline flex items-center space-x-1 text-xs text-gray-500 dark:text-gray-500"
							on:click={() => {
								showChangelog.set(true);
							}}
						>
							<div>{$i18n.t("See what's new")}</div>
						</button>
					{/if}
				</div>

				{#if $config?.features?.enable_version_update_check}
					<button
						class=" text-xs px-3 py-1.5 bg-gray-100 hover:bg-gray-200 dark:bg-gray-850 dark:hover:bg-gray-800 transition rounded-lg font-medium"
						on:click={() => {
							checkForVersionUpdates();
						}}
					>
						{$i18n.t('Check for updates')}
					</button>
				{/if}
			</div>
		</div>

		{#if ollamaVersion}
			<hr class=" border-gray-100/30 dark:border-gray-850/30" />

			<div>
				<div class=" mb-2.5 text-sm font-medium">{$i18n.t('Ollama Version')}</div>
				<div class="flex w-full">
					<div class="flex-1 text-xs text-gray-700 dark:text-gray-200">
						{ollamaVersion ?? 'N/A'}
					</div>
				</div>
			</div>
		{/if}

		<hr class=" border-gray-100/30 dark:border-gray-850/30" />

		{#if $config?.license_metadata}
			<div class="mb-2 text-xs">
				{#if !$WEBUI_NAME.includes('Open WebUI')}
					<span class=" text-gray-500 dark:text-gray-300 font-medium">{$WEBUI_NAME}</span> -
				{/if}

				<span class=" capitalize">{$config?.license_metadata?.type}</span> license purchased by
				<span class=" capitalize">{$config?.license_metadata?.organization_name}</span>
			</div>
		{:else}
			<!-- Sunway: Open WebUI community badges hidden for the internal rollout. These are
			     PROMOTIONAL (join Discord / follow X / star the repo), not the attribution the
			     licence requires — that is the "Powered by Open WebUI v{WEBUI_VERSION}" line
			     above, which is DELIBERATELY RETAINED (LICENSE clause 4). The copyright and
			     author-credit blocks below were hidden separately on request; the Twemoji
			     credit below is KEPT (CC-BY, unrelated to Open WebUI — see the note there).
			     These badges also each load an image from img.shields.io, i.e. an outbound
			     third-party request from every staff member opening Settings.
			     Hidden, not deleted. -->
			{#if false}
				<div class="flex space-x-1">
					<a href="https://discord.gg/5rJgQTnV4s" target="_blank">
						<img
							alt="Discord"
							src="https://img.shields.io/badge/Discord-Open_WebUI-blue?logo=discord&logoColor=white"
						/>
					</a>

					<a href="https://twitter.com/OpenWebUI" target="_blank">
						<img
							alt="X (formerly Twitter) Follow"
							src="https://img.shields.io/twitter/follow/OpenWebUI"
						/>
					</a>

					<a href="https://github.com/open-webui/open-webui" target="_blank">
						<img
							alt="Github Repo"
							src="https://img.shields.io/github/stars/open-webui/open-webui?style=social&label=Star us on Github"
						/>
					</a>
				</div>
			{/if}
		{/if}

		<!-- Sunway: KEPT ON PURPOSE (re-enabled 2026-07-31 after verifying actual usage).
		     This is a CC-BY 4.0 attribution and has NOTHING to do with Open WebUI. schat
		     really does use Twemoji: utils/pdf_generator.py registers Twemoji.ttf as a
		     fallback font (pdf.add_font('Twemoji', ...) / set_fallback_fonts) so emoji render
		     in the per-chat PDF download, and static/assets/pdf-style.css lists it in the
		     font stack. CC-BY requires attribution wherever the work is used, so this line
		     stays for as long as we ship those assets. To remove it, drop the Twemoji font +
		     emoji SVGs first and fall back to system emoji. -->
		<div class="mt-2 text-xs text-gray-400 dark:text-gray-500">
			Emoji graphics provided by
			<a href="https://github.com/jdecked/twemoji" target="_blank">Twemoji</a>, licensed under
			<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank">CC-BY 4.0</a>.
		</div>

		<!-- Sunway: Open WebUI copyright notice + author credit hidden on request (confirmed
		     2026-07-31). The "Powered by Open WebUI v{WEBUI_VERSION}" line ABOVE is
		     deliberately RETAINED as the LICENSE clause-4 attribution.
		     ⚠️ Note (open item, sunway-schat-notes.md §1): the copyright notice + LICENSE
		     link are the notice-retention part of the upstream licence — a separate
		     obligation from the clause-4 branding rule the "Powered by" line satisfies.
		     Hidden, not deleted — restore by dropping the {#if false} guard. -->
		{#if false}
			<div>
				<pre
					class="text-xs text-gray-400 dark:text-gray-500">Copyright (c) {new Date().getFullYear()} <a
						href="https://openwebui.com"
						target="_blank"
						class="underline">Open WebUI Inc.</a
					> <a href="https://github.com/open-webui/open-webui/blob/main/LICENSE" target="_blank"
						>All rights reserved.</a
					>
</pre>
			</div>

			<div class="mt-2 text-xs text-gray-400 dark:text-gray-500">
				{$i18n.t('Created by')}
				<a
					class=" text-gray-500 dark:text-gray-300 font-medium"
					href="https://github.com/tjbck"
					target="_blank">Timothy J. Baek</a
				>
			</div>
		{/if}
	</div>
</div>
