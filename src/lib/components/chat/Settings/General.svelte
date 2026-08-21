<script lang="ts">
	import Select from '$lib/components/common/Select.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher, onMount, getContext } from 'svelte';
	import { getLanguages, changeLanguage, SUPPORTED_LOCALES } from '$lib/i18n';
	const dispatch = createEventDispatcher();

	import { config, models, settings, theme, user } from '$lib/stores';

	const i18n = getContext('i18n');

	import AdvancedParams from './Advanced/AdvancedParams.svelte';
	import Textarea from '$lib/components/common/Textarea.svelte';
	export let saveSettings: Function;
	export let getModels: Function;

	// General
	let themes = ['dark', 'light', 'oled-dark'];
	let selectedTheme = 'system';

	// Sunway: System + Dark only (see the comment on the picker below for what is filtered
	// and why). Kept as data so the picker can be the shared Select component.
	const themeOptions = [
		{ value: 'system', label: '⚙️ System' },
		{ value: 'dark', label: '🌑 Dark' }
		// Removed from the picker, kept here so restoring one is a single uncomment. The
		// themeChangeHandler and the CSS for all of them are untouched, so any of these works
		// again immediately:
		// { value: 'oled-dark', label: '🌃 OLED Dark' },
		// { value: 'light', label: '☀️ Light' },
		// { value: 'her', label: '🌷 Her' }   // gated on config.features.enable_easter_eggs
	];

	// Sunway: the only locales offered in the language picker (see the filter in onMount).
	// en-GB rather than en-US — Malaysian business English uses British spelling.
	// Locale files for every other language are kept; add a code to SUPPORTED_LOCALES in
	// src/lib/i18n/index.ts to re-offer one — that same list drives i18next detection and
	// the strings i18next-parser generates, so the three stay in step.
	const ALLOWED_LANGUAGE_CODES = SUPPORTED_LOCALES;

	let languages: Awaited<ReturnType<typeof getLanguages>> = [];
	let lang = $i18n.language;
	let notificationEnabled = false;
	let system = '';

	let showAdvanced = false;

	const toggleNotification = async () => {
		const permission = await Notification.requestPermission();

		if (permission === 'granted') {
			notificationEnabled = !notificationEnabled;
			saveSettings({ notificationEnabled: notificationEnabled });
		} else {
			toast.error(
				$i18n.t(
					'Response notifications cannot be activated as the website permissions have been denied. Please visit your browser settings to grant the necessary access.'
				)
			);
		}
	};

	let params = {
		// Advanced
		stream_response: null,
		stream_delta_chunk_size: null,
		function_calling: null,
		reasoning_tags: null,
		seed: null,
		temperature: null,
		reasoning_effort: null,
		logit_bias: null,
		frequency_penalty: null,
		presence_penalty: null,
		repeat_penalty: null,
		repeat_last_n: null,
		mirostat: null,
		mirostat_eta: null,
		mirostat_tau: null,
		top_k: null,
		top_p: null,
		min_p: null,
		stop: null,
		tfs_z: null,
		num_ctx: null,
		num_batch: null,
		num_keep: null,
		max_tokens: null,
		use_mmap: null,
		use_mlock: null,
		num_thread: null,
		num_gpu: null,
		think: null,
		format: null,
		keep_alive: null
	};

	const saveHandler = async () => {
		saveSettings({
			system: system !== '' ? system : undefined,
			params: {
				stream_response: params.stream_response !== null ? params.stream_response : undefined,
				stream_delta_chunk_size:
					params.stream_delta_chunk_size !== null ? params.stream_delta_chunk_size : undefined,
				function_calling: params.function_calling !== null ? params.function_calling : undefined,
				reasoning_tags: params.reasoning_tags !== null ? params.reasoning_tags : undefined,
				seed: (params.seed !== null ? params.seed : undefined) ?? undefined,
				stop: params.stop ? params.stop.split(',').filter((e) => e) : undefined,
				temperature: params.temperature !== null ? params.temperature : undefined,
				reasoning_effort: params.reasoning_effort !== null ? params.reasoning_effort : undefined,
				logit_bias: params.logit_bias !== null ? params.logit_bias : undefined,
				frequency_penalty: params.frequency_penalty !== null ? params.frequency_penalty : undefined,
				presence_penalty: params.presence_penalty !== null ? params.presence_penalty : undefined,
				repeat_penalty: params.repeat_penalty !== null ? params.repeat_penalty : undefined,
				repeat_last_n: params.repeat_last_n !== null ? params.repeat_last_n : undefined,
				mirostat: params.mirostat !== null ? params.mirostat : undefined,
				mirostat_eta: params.mirostat_eta !== null ? params.mirostat_eta : undefined,
				mirostat_tau: params.mirostat_tau !== null ? params.mirostat_tau : undefined,
				top_k: params.top_k !== null ? params.top_k : undefined,
				top_p: params.top_p !== null ? params.top_p : undefined,
				min_p: params.min_p !== null ? params.min_p : undefined,
				tfs_z: params.tfs_z !== null ? params.tfs_z : undefined,
				num_ctx: params.num_ctx !== null ? params.num_ctx : undefined,
				num_batch: params.num_batch !== null ? params.num_batch : undefined,
				num_keep: params.num_keep !== null ? params.num_keep : undefined,
				max_tokens: params.max_tokens !== null ? params.max_tokens : undefined,
				use_mmap: params.use_mmap !== null ? params.use_mmap : undefined,
				use_mlock: params.use_mlock !== null ? params.use_mlock : undefined,
				num_thread: params.num_thread !== null ? params.num_thread : undefined,
				num_gpu: params.num_gpu !== null ? params.num_gpu : undefined,
				think: params.think !== null ? params.think : undefined,
				keep_alive: params.keep_alive !== null ? params.keep_alive : undefined,
				format: params.format !== null ? params.format : undefined,
				...(params.custom_params && Object.keys(params.custom_params).length > 0
					? { custom_params: params.custom_params }
					: {})
			}
		});
		dispatch('save');
	};

	onMount(async () => {
		selectedTheme = localStorage.theme ?? 'system';

		languages = await getLanguages();

		if (!$config?.features?.enable_easter_eggs) {
			languages = languages.filter((l) => l.code !== 'dg-DG');
		}

		// Sunway: the picker offers ~60 locales, almost all irrelevant to a Malaysian
		// workforce and most only partially translated. Narrowed to the three that matter.
		// Nothing is deleted — every locale file stays in src/lib/i18n/locales and the
		// switcher is unchanged, so widening this list is the only step to restore one.
		// en-GB over en-US: Malaysian business English follows British spelling.
		languages = languages.filter((l) => ALLOWED_LANGUAGE_CODES.includes(l.code));

		notificationEnabled = $settings.notificationEnabled ?? false;
		system = $settings.system ?? '';

		params = { ...params, ...$settings.params };
		params.stop = $settings?.params?.stop ? ($settings?.params?.stop ?? []).join(',') : null;
	});

	const applyTheme = (_theme: string) => {
		let themeToApply = _theme === 'oled-dark' ? 'dark' : _theme === 'her' ? 'light' : _theme;

		if (_theme === 'system') {
			themeToApply = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
		}

		if (themeToApply === 'dark' && !_theme.includes('oled')) {
			document.documentElement.style.setProperty('--color-gray-800', '#333');
			document.documentElement.style.setProperty('--color-gray-850', '#262626');
			document.documentElement.style.setProperty('--color-gray-900', '#171717');
			document.documentElement.style.setProperty('--color-gray-950', '#0d0d0d');
		}

		themes
			.filter((e) => e !== themeToApply)
			.forEach((e) => {
				e.split(' ').forEach((e) => {
					document.documentElement.classList.remove(e);
				});
			});

		themeToApply.split(' ').forEach((e) => {
			document.documentElement.classList.add(e);
		});

		const metaThemeColor = document.querySelector('meta[name="theme-color"]');
		if (metaThemeColor) {
			if (_theme.includes('system')) {
				const systemTheme = window.matchMedia('(prefers-color-scheme: dark)').matches
					? 'dark'
					: 'light';
				console.log('Setting system meta theme color: ' + systemTheme);
				metaThemeColor.setAttribute('content', systemTheme === 'light' ? '#ffffff' : '#171717');
			} else {
				console.log('Setting meta theme color: ' + _theme);
				metaThemeColor.setAttribute(
					'content',
					_theme === 'dark'
						? '#171717'
						: _theme === 'oled-dark'
							? '#000000'
							: _theme === 'her'
								? '#983724'
								: '#ffffff'
				);
			}
		}

		if (typeof window !== 'undefined' && window.applyTheme) {
			window.applyTheme();
		}

		if (_theme.includes('oled')) {
			document.documentElement.style.setProperty('--color-gray-800', '#101010');
			document.documentElement.style.setProperty('--color-gray-850', '#050505');
			document.documentElement.style.setProperty('--color-gray-900', '#000000');
			document.documentElement.style.setProperty('--color-gray-950', '#000000');
			document.documentElement.classList.add('dark');
		}

		console.log(_theme);
	};

	const themeChangeHandler = (_theme: string) => {
		theme.set(_theme);
		localStorage.setItem('theme', _theme);
		applyTheme(_theme);
	};
</script>

<div class="flex flex-col h-full justify-between text-sm" id="tab-general">
	<div class="  overflow-y-scroll max-h-[28rem] md:max-h-full">
		<div class="">
			<div class=" mb-1.5 text-sm font-medium">{$i18n.t('Settings')}</div>

			<!-- Sunway: the three preference rows sit in a card with separators instead of floating
			     in an otherwise empty panel, and the two native <select>s are the shared Select
			     component so they stop rendering with the OS dropdown (and its blue highlight)
			     inside a dark modal. Behaviour is unchanged: same bindings, same handlers.
			     Theme choices are still trimmed to System + Dark; the removed options are kept as
			     commented entries in themeOptions above, so restoring one is a single uncomment.
			     "System" still resolves to light when the OS is light — this only removes the
			     manual pickers. -->
			<div class="brand-surface rounded-2xl px-3 divide-y divide-[var(--brand-neutral)]">
				<div class="flex w-full justify-between items-center py-2">
					<div class=" self-center text-xs font-medium">{$i18n.t('Theme')}</div>
					<Select
						bind:value={selectedTheme}
						items={themeOptions}
						align="end"
						triggerClass="brand-pill-outline"
						onChange={() => themeChangeHandler(selectedTheme)}
					>
						<svelte:fragment slot="trigger" let:selectedLabel>
							<span class="truncate">{selectedLabel}</span>
							<ChevronDown className="size-3" strokeWidth="2.5" />
						</svelte:fragment>
					</Select>
				</div>

				<!-- Sunway: the Language picker is hidden. Team decision -- schat ships one
				     language, en-GB (Malaysian business English is British-spelled), so this was a
				     control whose only outcomes were "no change" or "a partially translated UI".
				     The hiding is cosmetic; what actually enforces it is SUPPORTED_LOCALES in
				     lib/i18n/index.ts being en-GB alone, which makes a stale localStorage value or
				     a ?lang= query string resolve back to en-GB. Restore by unwrapping this guard
				     AND adding the codes back to SUPPORTED_LOCALES -- unwrapping alone gives a
				     picker whose other options silently do nothing. -->
				{#if false}
					<div class=" flex w-full justify-between items-center py-2">
						<div class=" self-center text-xs font-medium">{$i18n.t('Language')}</div>
						<Select
							bind:value={lang}
							items={languages.map((language) => ({
								value: language['code'],
								label: language['title']
							}))}
							align="end"
							triggerClass="brand-pill-outline"
							onChange={() => {
								changeLanguage(lang);
							}}
						>
							<svelte:fragment slot="trigger" let:selectedLabel>
								<span class="truncate">{selectedLabel}</span>
								<ChevronDown className="size-3" strokeWidth="2.5" />
							</svelte:fragment>
						</Select>
					</div>
				{/if}
				{#if $i18n.language === 'en-US' && !($config?.license_metadata ?? false)}
					<div
						class="mb-2 text-xs {($settings?.highContrastMode ?? false)
							? 'text-gray-800 dark:text-gray-100'
							: 'text-gray-400 dark:text-gray-500'}"
					>
						Couldn't find your language?
						<a
							class="font-medium underline {($settings?.highContrastMode ?? false)
								? 'text-gray-700 dark:text-gray-200'
								: 'text-gray-300'}"
							href="https://github.com/open-webui/open-webui/blob/main/docs/CONTRIBUTING.md#-translations-and-internationalization"
							target="_blank"
						>
							Help us translate Open WebUI!
						</a>
					</div>
				{/if}

				<div>
					<div class=" flex w-full justify-between items-center py-2">
						<div class=" self-center text-xs font-medium">{$i18n.t('Notifications')}</div>

						<button
							class="brand-pill-outline"
							on:click={() => {
								toggleNotification();
							}}
							type="button"
							role="switch"
							aria-checked={notificationEnabled}
						>
							{#if notificationEnabled === true}
								<span class="self-center">{$i18n.t('On')}</span>
							{:else}
								<span class="self-center">{$i18n.t('Off')}</span>
							{/if}
						</button>
					</div>
				</div>
			</div>
		</div>

		<!-- Sunway: user-level System Prompt hidden for everyone incl. admins — it silently layers
		     on top of the team-configured model system prompts and would skew curated behavior.
		     Model-level prompts live in Admin Settings → Models. See CLAUDE.md.
		     Original gate was: admin OR (chat.controls AND chat.system_prompt) -->
		{#if false}
			<hr class="border-gray-100/30 dark:border-gray-850/30 my-3" />

			<div>
				<div class=" my-2.5 text-sm font-medium">{$i18n.t('System Prompt')}</div>
				<Textarea
					bind:value={system}
					className={'w-full text-sm outline-hidden resize-vertical' +
						($settings.highContrastMode
							? ' p-2.5 border-2 border-gray-300 dark:border-gray-700 rounded-lg bg-transparent text-gray-900 dark:text-gray-100 focus:ring-1 focus:ring-blue-500 focus:border-blue-500 overflow-y-hidden'
							: '  dark:text-gray-300 ')}
					rows="4"
					placeholder={$i18n.t('Enter system prompt here')}
				/>
			</div>
		{/if}

		<!-- Sunway: user-level Advanced Parameters hidden for everyone incl. admins — same rationale
		     as the per-chat Controls hide; model-level params live in Admin Settings → Models.
		     Original gate was: admin OR (chat.controls AND chat.params) -->
		{#if false}
			<div class="mt-2 space-y-3 pr-1.5">
				<div class="flex justify-between items-center text-sm">
					<div class="  font-medium">{$i18n.t('Advanced Parameters')}</div>
					<button
						class=" text-xs font-medium {($settings?.highContrastMode ?? false)
							? 'text-gray-800 dark:text-gray-100'
							: 'text-gray-400 dark:text-gray-500'}"
						type="button"
						aria-expanded={showAdvanced}
						on:click={() => {
							showAdvanced = !showAdvanced;
						}}>{showAdvanced ? $i18n.t('Hide') : $i18n.t('Show')}</button
					>
				</div>

				{#if showAdvanced}
					<AdvancedParams admin={$user?.role === 'admin'} custom={true} bind:params />
				{/if}
			</div>
		{/if}
	</div>

	<div class="flex justify-end pt-3 text-sm font-medium">
		<button
			class="px-3.5 py-1.5 text-sm font-medium brand-btn-primary brand-nav-item transition rounded-full"
			on:click={() => {
				saveHandler();
			}}
		>
			{$i18n.t('Save')}
		</button>
	</div>
</div>
