<script lang="ts">
	import { models, showSettings, settings, user, mobile, config } from '$lib/stores';
	import { onMount, tick, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import Selector from './ModelSelector/Selector.svelte';
	import Tooltip from '../common/Tooltip.svelte';

	import { updateUserSettings } from '$lib/apis/users';
	import equal from 'fast-deep-equal';
	const i18n = getContext('i18n');

	export let selectedModels = [''];
	export let disabled = false;

	export let showSetDefault = true;

	// Sunway: `compact` renders the selector for the composer (beside Send) rather than the chat
	// navbar — it shrinks to its content so it sits in the button row without stretching it.
	// Behaviour is otherwise identical. See CLAUDE.md → "Deferred / hidden features".
	export let compact = false;

	// Sunway: explicit tier order for the picker — everyday first, then reasoning, then coding,
	// which is the ordering the SOTA assistants use and the order the tiers are meant to be
	// reached for.
	//
	// This is NOT cosmetic sugar over an existing order: there is no ordering anywhere in the
	// stack to override. Models.get_all_models() (backend/open_webui/models/models.py) runs a
	// bare `select(Model)` with NO ORDER BY, utils/models.py appends the rows in whatever order
	// they come back, and nothing sorts them afterwards. So the picker inherited raw Postgres
	// heap order — unspecified by definition, and NOT stable: Postgres rewrites a row on UPDATE,
	// so editing any model could silently reshuffle the list. All three tiers also share one
	// created_at, so no timestamp sort would separate them either.
	//
	// Ids, not names: names are display strings and are localised/renamable, ids are the stable
	// key. Same convention as ALLOWED_LANGUAGE_CODES / HIDDEN_SHORTCUT_IDS elsewhere in the fork.
	// Anything not listed sorts after these, alphabetically, so the order is fully deterministic
	// for base models and any future tier rather than falling back to DB order.
	const MODEL_TIER_ORDER = ['schat-quick', 'schat-deepthink', 'schat-coding'];

	const tierRank = (id: string) => {
		const idx = MODEL_TIER_ORDER.indexOf(id);
		return idx === -1 ? MODEL_TIER_ORDER.length : idx;
	};

	const saveDefaultModel = async () => {
		const hasEmptyModel = selectedModels.filter((it) => it === '');
		if (hasEmptyModel.length) {
			toast.error($i18n.t('Choose a model before saving...'));
			return;
		}
		settings.set({ ...$settings, models: selectedModels });
		await updateUserSettings(localStorage.token, { ui: $settings });

		toast.success($i18n.t('Default model updated'));
	};

	const pinModelHandler = async (modelId) => {
		let pinnedModels = $settings?.pinnedModels ?? [];

		if (pinnedModels.includes(modelId)) {
			pinnedModels = pinnedModels.filter((id) => id !== modelId);
		} else {
			pinnedModels = [...new Set([...pinnedModels, modelId])];
		}

		settings.set({ ...$settings, pinnedModels: pinnedModels });
		await updateUserSettings(localStorage.token, { ui: $settings });
	};

	$: if (selectedModels.length > 0 && $models.length > 0) {
		const _selectedModels = selectedModels.map((model) =>
			$models.map((m) => m.id).includes(model) ? model : ''
		);

		if (!equal(_selectedModels, selectedModels)) {
			selectedModels = _selectedModels;
		}
	}
</script>

<div class="flex flex-col items-start {compact ? 'w-fit' : 'w-full'}">
	{#each selectedModels as selectedModel, selectedModelIdx}
		<div class="flex w-full max-w-fit">
			<div class="overflow-hidden w-full">
				<div class="max-w-full {($settings?.highContrastMode ?? false) ? 'm-1' : 'mr-1'}">
					<!-- Sunway: searchEnabled={false} — an EXISTING upstream prop (Selector.svelte
					     defaults it true), so no new gate. The picker lists exactly three curated
					     tiers (Flash / Coder / Deepthink); a search box over three items is noise,
					     and it also carried the "Pull {model} from Ollama.com" affordance, which is
					     dead here (Ollama is deployed nowhere — chart pins ENABLE_OLLAMA_API=false). -->
					<Selector
						id={`${selectedModelIdx}`}
						placeholder={$i18n.t('Select a model')}
						searchEnabled={false}
						triggerClassName={compact ? 'text-lg' : 'text-lg'}
						items={$models
							.map((model) => ({
								value: model.id,
								label: model.name,
								model: model
							}))
							.sort(
								(a, b) =>
									tierRank(a.value) - tierRank(b.value) ||
									(a.label ?? '').localeCompare(b.label ?? '')
							)}
						{pinModelHandler}
						bind:value={selectedModel}
					/>
				</div>
			</div>

			<!-- Sunway: multi-model responses removed for the rollout. The "+" below adds a second
			     model to the same turn, fanning the prompt out to every selected model and
			     rendering side-by-side responses with a merge action. Out of scope: it multiplies
			     token spend per turn, and the merge step attributes generated text to no single
			     served model.
			     Replaced the upstream gate (role === 'admin' || permissions.chat.multiple_models)
			     rather than the permission itself, because `admin` does NOT distinguish super
			     admin from BU admin under multi-tenancy — see CLAUDE.md. Hidden for EVERYONE.
			     `selectedModelIdx !== 0` deliberately, NOT `false`: the inner {:else} branch is
			     the "Remove Model" button. Gating the whole block off would also remove that,
			     stranding anyone whose chat already carries a second model (selectedModels is
			     restored from chat state) with no way to drop it. This keeps Remove reachable
			     while Add can never render. -->
			{#if selectedModelIdx !== 0}
				{#if selectedModelIdx === 0}
					<div
						class="  self-center mx-1 disabled:text-gray-600 disabled:hover:text-gray-600 -translate-y-[0.5px]"
					>
						<Tooltip content={$i18n.t('Add Model')}>
							<button
								class=" "
								{disabled}
								on:click={() => {
									selectedModels = [...selectedModels, ''];
								}}
								aria-label="Add Model"
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke-width="2"
									stroke="currentColor"
									class="size-3.5"
								>
									<path stroke-linecap="round" stroke-linejoin="round" d="M12 6v12m6-6H6" />
								</svg>
							</button>
						</Tooltip>
					</div>
				{:else}
					<div
						class="  self-center mx-1 disabled:text-gray-600 disabled:hover:text-gray-600 -translate-y-[0.5px]"
					>
						<Tooltip content={$i18n.t('Remove Model')}>
							<button
								{disabled}
								on:click={() => {
									selectedModels.splice(selectedModelIdx, 1);
									selectedModels = selectedModels;
								}}
								aria-label="Remove Model"
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke-width="2"
									stroke="currentColor"
									class="size-3"
								>
									<path stroke-linecap="round" stroke-linejoin="round" d="M19.5 12h-15" />
								</svg>
							</button>
						</Tooltip>
					</div>
				{/if}
			{/if}
		</div>
	{/each}
</div>

{#if showSetDefault}
	<div
		class="relative text-left mt-[1px] ml-1 text-[0.7rem] text-gray-600 dark:text-gray-400 font-primary"
	>
		<button on:click={saveDefaultModel}> {$i18n.t('Set as default')}</button>
	</div>
{/if}
