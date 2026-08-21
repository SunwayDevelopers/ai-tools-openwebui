<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher } from 'svelte';
	import { onMount, getContext } from 'svelte';
	import { addUser } from '$lib/apis/auths';
	import { config } from '$lib/stores';

	import { WEBUI_BASE_URL } from '$lib/constants';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import { generateInitialsImage } from '$lib/utils';
	import XMark from '$lib/components/icons/XMark.svelte';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;

	let loading = false;
	let tab = '';
	let inputFiles;

	let _user = {
		name: '',
		email: '',
		password: '',
		role: 'user'
	};

	$: if (show) {
		_user = {
			name: '',
			email: '',
			password: '',
			role: 'user'
		};
	}

	const submitHandler = async () => {
		const stopLoading = () => {
			dispatch('save');
			loading = false;
		};

		if (tab === '') {
			loading = true;

			const res = await addUser(
				localStorage.token,
				_user.name,
				_user.email,
				_user.password,
				_user.role,
				generateInitialsImage(_user.name)
			).catch((error) => {
				toast.error(`${error}`);
			});

			if (res) {
				stopLoading();
				show = false;
			}
		} else {
			if (inputFiles) {
				loading = true;

				const file = inputFiles[0];
				const reader = new FileReader();

				reader.onload = async (e) => {
					const csv = e.target.result;
					const rows = csv.split('\n');

					let userCount = 0;

					for (const [idx, row] of rows.entries()) {
						const columns = row.split(',').map((col) => col.trim());
						console.debug(idx, columns);

						// Sunway: the format is Name, Email, Role -- the Password column is gone (2026-08-21).
						// schat does not own passwords: identity is IAM's, and the Add User form stopped
						// collecting one for everyone. A password column in a bulk-import file is a
						// plaintext credential list circulating as a spreadsheet, for a credential nothing
						// honours. An empty string is passed instead and the backend generates an unusable
						// random secret (routers/auths.py add_user).
						//
						// 'pending' is not accepted here, matching the Form tab's role picker: it is
						// upstream's signup-approval state and an account created in it cannot sign in.
						if (idx > 0 && row.trim() !== '') {
							if (columns.length === 3 && ['admin', 'user'].includes(columns[2].toLowerCase())) {
								const res = await addUser(
									localStorage.token,
									columns[0],
									columns[1],
									'',
									columns[2].toLowerCase(),
									generateInitialsImage(columns[0])
								).catch((error) => {
									toast.error(`Row ${idx + 1}: ${error}`);
									return null;
								});

								if (res) {
									userCount = userCount + 1;
								}
							} else {
								toast.error(`Row ${idx + 1}: invalid format.`);
							}
						}
					}

					toast.success(
						$i18n.t('Successfully imported {{userCount}} users.', { userCount: userCount })
					);
					inputFiles = null;
					const uploadInputElement = document.getElementById('upload-user-csv-input');

					if (uploadInputElement) {
						uploadInputElement.value = null;
					}

					stopLoading();
				};

				reader.readAsText(file, 'utf-8');
			} else {
				toast.error($i18n.t('File not found.'));
			}
		}

		loading = false;
	};
</script>

<Modal size="sm" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-5 pt-4 pb-2">
			<div class=" text-lg font-medium self-center">{$i18n.t('Add User')}</div>
			<button
				class="self-center"
				aria-label={$i18n.t('Close')}
				on:click={() => {
					show = false;
				}}
			>
				<XMark className={'size-5'} />
			</button>
		</div>

		<div class="flex flex-col md:flex-row w-full px-4 pb-3 md:space-x-4 dark:text-gray-200">
			<div class=" flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
				<form
					class="flex flex-col w-full"
					on:submit|preventDefault={() => {
						submitHandler();
					}}
				>
					<!-- Sunway: CSV Import restored 2026-08-21, with the Password column dropped from
					     the format (see the parser above). It was hidden because the file carried
					     plaintext passwords schat does not own under IAM; without that column it is an
					     ordinary bulk-provisioning list of Name, Email, Role.

					     The Role column still admits 'admin', so this file can mint admins -- that is
					     the point of it for an operator provisioning a tenant, and it is the same
					     capability the Form tab's role picker already has. -->
					{#if true}
						<div
							class="flex -mt-2 mb-1.5 gap-1 scrollbar-none overflow-x-auto w-fit text-center text-sm font-medium rounded-full bg-transparent dark:text-gray-200"
						>
							<button
								class="min-w-fit p-1.5 {tab === ''
									? ''
									: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition"
								type="button"
								on:click={() => {
									tab = '';
								}}>{$i18n.t('Form')}</button
							>

							<button
								class="min-w-fit p-1.5 {tab === 'import'
									? ''
									: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition"
								type="button"
								on:click={() => {
									tab = 'import';
								}}>{$i18n.t('CSV Import')}</button
							>
						</div>
					{/if}

					<div class="px-1">
						{#if tab === ''}
							<div class="flex flex-col w-full mb-3">
								<div class=" mb-1 text-xs text-gray-500">{$i18n.t('Role')}</div>

								<div class="flex-1">
									<select
										class="w-full capitalize rounded-lg text-sm bg-transparent dark:disabled:text-gray-500 outline-hidden"
										bind:value={_user.role}
										aria-label={$i18n.t('Role')}
										placeholder={$i18n.t('Enter Your Role')}
										required
									>
										<!-- Sunway: "pending" removed from the picker. It is upstream's
										     signup-approval state; schat provisions accounts from here (or from
										     IAM), so creating one that cannot sign in is a support ticket, not a
										     workflow. The role value itself still exists server-side. -->
										<option value="user"> {$i18n.t('user')} </option>
										<option value="admin"> {$i18n.t('admin')} </option>
									</select>
								</div>
							</div>

							<div class="flex flex-col w-full mt-1">
								<div class=" mb-1 text-xs text-gray-500">{$i18n.t('Name')}</div>

								<div class="flex-1">
									<input
										class="w-full text-sm bg-transparent disabled:text-gray-500 dark:disabled:text-gray-500 outline-hidden"
										type="text"
										bind:value={_user.name}
										aria-label={$i18n.t('Name')}
										placeholder={$i18n.t('Enter Your Full Name')}
										autocomplete="off"
										required
									/>
								</div>
							</div>

							<hr class=" border-gray-100/30 dark:border-gray-850/30 my-2.5 w-full" />

							<div class="flex flex-col w-full">
								<div class=" mb-1 text-xs text-gray-500">{$i18n.t('Email')}</div>

								<div class="flex-1">
									<input
										class="w-full text-sm bg-transparent disabled:text-gray-500 dark:disabled:text-gray-500 outline-hidden"
										type="email"
										bind:value={_user.email}
										aria-label={$i18n.t('Email')}
										placeholder={$i18n.t('Enter Your Email')}
										required
									/>
								</div>
							</div>

							<!-- Sunway: the password field is hidden outright. It was already absent
							     wherever ENABLE_MULTI_TENANCY is on (staging and production), so this only
							     removes it from environments with MT off — dev machines — where a locally
							     set password is not a credential anything honours. Identity comes from IAM.
							     Original gate was: !config.features.enable_multi_tenancy -->
							{#if false}
								<div class="flex flex-col w-full mt-1">
									<div class=" mb-1 text-xs text-gray-500">{$i18n.t('Password')}</div>

									<div class="flex-1">
										<SensitiveInput
											class="w-full text-sm bg-transparent disabled:text-gray-500 dark:disabled:text-gray-500 outline-hidden"
											type="password"
											bind:value={_user.password}
											aria-label={$i18n.t('Password')}
											placeholder={$i18n.t('Enter Your Password')}
											autocomplete="off"
											required
										/>
									</div>
								</div>
							{/if}
						{:else if tab === 'import'}
							<div>
								<div class="mb-3 w-full">
									<input
										id="upload-user-csv-input"
										hidden
										bind:files={inputFiles}
										type="file"
										accept=".csv"
									/>

									<button
										class="w-full text-sm font-medium py-3 bg-transparent brand-nav-item border border-dashed dark:border-gray-850 brand-nav-item text-center rounded-xl"
										type="button"
										on:click={() => {
											document.getElementById('upload-user-csv-input')?.click();
										}}
									>
										{#if inputFiles}
											{inputFiles.length > 0 ? `${inputFiles.length}` : ''} document(s) selected.
										{:else}
											{$i18n.t('Click here to select a csv file.')}
										{/if}
									</button>
								</div>

								<div class=" text-xs text-gray-500">
									ⓘ {$i18n.t(
										'Ensure your CSV file includes 3 columns in this order: Name, Email, Role.'
									)}
									<a
										class="underline dark:text-gray-200"
										href="{WEBUI_BASE_URL}/static/user-import.csv"
									>
										{$i18n.t('Click here to download user import template file.')}
									</a>
								</div>
							</div>
						{/if}
					</div>

					<div class="flex justify-end pt-3 text-sm font-medium">
						<button
							class="px-3.5 py-1.5 text-sm font-medium brand-btn-primary brand-nav-item transition rounded-full flex items-center gap-2 whitespace-nowrap {loading
								? ' cursor-not-allowed'
								: ''}"
							type="submit"
							disabled={loading}
						>
							{$i18n.t('Save')}

							{#if loading}
								<span class="shrink-0">
									<Spinner />
								</span>
							{/if}
						</button>
					</div>
				</form>
			</div>
		</div>
	</div>
</Modal>

<style>
	input::-webkit-outer-spin-button,
	input::-webkit-inner-spin-button {
		/* display: none; <- Crashes Chrome on hover */
		-webkit-appearance: none;
		margin: 0; /* <-- Apparently some margin are still there even though it's hidden */
	}

	.tabs::-webkit-scrollbar {
		display: none; /* for Chrome, Safari and Opera */
	}

	.tabs {
		-ms-overflow-style: none; /* IE and Edge */
		scrollbar-width: none; /* Firefox */
	}

	input[type='number'] {
		-moz-appearance: textfield; /* Firefox */
	}
</style>
