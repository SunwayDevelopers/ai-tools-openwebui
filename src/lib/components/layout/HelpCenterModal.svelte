<script lang="ts">
	import { getContext } from 'svelte';

	import Modal from '../common/Modal.svelte';
	import XMark from '../icons/XMark.svelte';
	import Search from '../icons/Search.svelte';
	import ChevronDown from '../icons/ChevronDown.svelte';
	import { SCHAT_FEEDBACK_URL } from '$lib/constants';
	import { config } from '$lib/stores';

	const i18n = getContext('i18n');

	export let show = false;

	// Sunway: the FAQ is a plain array in the component, mirroring sdeck's Help.tsx. Deliberately
	// NOT i18n keys: these are long prose answers that would bloat the locale catalogue with
	// strings nobody is going to translate, and schat generates only en-GB (SUPPORTED_LOCALES in
	// lib/i18n/index.ts). The chrome around the answers IS translated.
	//
	// Every number that appears in an answer is interpolated from the live /api/config payload
	// rather than typed into the prose, so the help text cannot contradict the deployment it is
	// being read on. Only the wording is hard-coded -- and that part does go stale silently, since
	// nothing ties it to the feature flags.
	type Faq = { category: string; question: string; answer: string };

	$: maxChats = $config?.retention?.max_chats_per_user ?? 30;
	$: retentionDays = $config?.retention?.chat_retention_days ?? 30;
	$: maxFileCount = $config?.file?.max_count ?? 10;
	$: maxFileSize = $config?.file?.max_size ?? 30;

	const FAQS: Faq[] = [
		{
			category: 'Getting started',
			question: 'What is SChat.ai?',
			answer:
				'SChat.ai is Sunway’s internal AI assistant. It runs on models hosted inside Sunway’s own infrastructure, so your conversations, uploaded documents and knowledge bases stay within the organisation and are not sent to an external AI provider.'
		},
		{
			category: 'Getting started',
			question: 'Which model should I pick — Flash or Deepthink?',
			answer:
				'Flash is the default and the right choice for almost everything: questions, drafting, summarising, rewriting and quick lookups. It answers immediately.\n\nDeepthink works through a problem step by step before replying. It is noticeably slower, so use it for analysis, multi-step reasoning, comparing options, or anything where you would rather wait and get a more careful answer.\n\nYou can switch models at any time using the selector next to the send button. Switching does not clear the conversation.'
		},
		{
			category: 'Getting started',
			question: 'Does it know today’s date and recent events?',
			answer:
				'It knows the current date. For anything recent or changing, turn on Web Search so it looks the answer up rather than relying on what it learnt during training.\n\nWithout web search it can only answer from training data, which has a cut-off, and from whatever you have attached to the conversation.'
		},
		{
			category: 'Chats',
			question: 'How many chats can I keep?',
			answer:
				'You can keep up to {{MAX_CHATS}} chats. Once you reach the limit you will need to delete an existing chat before starting a new one.\n\nThis is a hard limit and it applies to everyone, administrators included.'
		},
		{
			category: 'Chats',
			question: 'Why did my old chats disappear?',
			answer:
				'Chats are removed automatically after {{RETENTION_DAYS}} days of inactivity. The clock runs from the last time a chat was updated, not from when it was created — so a conversation you keep coming back to will not expire.\n\nIf a chat matters beyond that window, download it while it is still there (chat menu → Download) or move the important content somewhere permanent.'
		},
		{
			category: 'Chats',
			question: 'Can I save or export a conversation?',
			answer:
				'Yes. Open the chat menu in the top bar and choose Download. You can save a chat as a PDF, as plain text, or as JSON.\n\nPDF and plain text are the readable formats and are what you want for sharing or filing. JSON is a technical format that preserves the full structure.'
		},
		{
			category: 'Chats',
			question: 'Can I edit a message after sending it?',
			answer:
				'You can edit your own messages — hover over one and use the edit icon, or press the up arrow in an empty input box to edit your last message. Editing re-runs the conversation from that point.\n\nYou cannot edit the assistant’s replies. That is deliberate: an edited AI response still looks like something the model said, which makes it easy to misattribute later. If a reply is wrong, ask for a correction or regenerate it.'
		},
		{
			category: 'Files',
			question: 'What file types can I upload?',
			answer:
				'PDF, DOCX, XLSX, PPTX, CSV, TXT, MD, PNG, JPG and JPEG.\n\nScanned PDFs and photographed documents are handled too — they are put through text recognition automatically, so you do not need to convert them first.'
		},
		{
			category: 'Files',
			question: 'How many files can I attach, and how large?',
			answer:
				'Up to {{MAX_FILE_COUNT}} files per chat, and up to {{MAX_FILE_SIZE}}MB each.\n\nIf a document is larger than that, split it, or extract the relevant section and paste it in directly.'
		},
		{
			category: 'Files',
			question: 'It cannot find something I know is in my document. Why?',
			answer:
				'For large documents the assistant retrieves the passages that look most relevant to your question rather than reading the file end to end. If your question is phrased differently from the wording in the document, the right passage may not surface.\n\nTwo things usually fix it: use the same terminology the document uses, and ask a narrower question. Asking about one section at a time works far better than asking for a summary of everything.\n\nIf the document is a scan, click the file to preview what was actually extracted and check the text was recognised correctly.'
		},
		{
			category: 'Files',
			question: 'What happens to files I upload?',
			answer:
				'They are stored with the chat and used to answer your questions in that conversation. They are removed together with the chat — either when you delete it, or when it expires after {{RETENTION_DAYS}} days of inactivity.\n\nUploads are visible only to you unless you have added them to a shared knowledge base.'
		},
		{
			category: 'Knowledge',
			question: 'What is a Knowledge Base and when should I use one?',
			answer:
				'A knowledge base is a reusable collection of documents. Attach it to a chat and the assistant can draw on all of it, without you re-uploading the same files every time.\n\nUse a chat upload for a one-off document. Use a knowledge base for material you or your team refer to repeatedly — policies, product documentation, standard procedures.'
		},
		{
			category: 'Knowledge',
			question: 'How do I attach a knowledge base to a chat?',
			answer:
				'Type # in the message box to bring up the picker, or use the + button next to the input and choose Attach Knowledge. The knowledge base stays attached for that conversation.'
		},
		{
			category: 'Web search',
			question: 'How do I get answers about current information?',
			answer:
				'Turn on Web Search in the message box, then ask your question. The assistant searches, reads the results and cites the pages it used — click a citation to open the source.\n\nCheck the citation for anything that matters. Web results vary in quality, and the assistant is summarising them, not vouching for them.'
		},
		{
			category: 'Images',
			question: 'Can it read images and screenshots?',
			answer:
				'Yes. Paste or upload a screenshot, photo or scanned page and ask about it. Text in the image is extracted automatically, which makes it useful for screenshots of error messages, forms, printed tables and whiteboards.'
		},
		{
			category: 'Images',
			question: 'Can it generate images?',
			answer:
				'Yes. Turn on the image option in the message box and describe what you want.\n\nGenerated images are illustrative. Do not rely on them for anything needing accurate text, logos, charts or figures — image models reproduce those unreliably.'
		},
		{
			category: 'Privacy',
			question: 'Is what I type private?',
			answer:
				'Your chats are yours. Administrators cannot open other people’s conversations through the interface, and the routes that previously allowed it have been removed.\n\nThe models run on Sunway-hosted infrastructure, so your prompts are not sent to an external AI provider.'
		},
		{
			category: 'Privacy',
			question: 'What if I accidentally paste something sensitive?',
			answer:
				'SChat.ai detects and masks several kinds of sensitive data before a message reaches the model and before it is stored — including NRIC numbers, email addresses, Malaysian phone numbers, payment card numbers, and credentials such as API keys and private keys. These show up as [REDACTED_…] markers.\n\nTreat it as a safety net, not a licence. It cannot recognise everything, so still avoid pasting personal data, credentials or confidential material you would not put in an internal email.'
		},
		{
			category: 'Settings',
			question: 'Can I change the language or the appearance?',
			answer:
				'Yes — Settings → General. The interface is available in English, Bahasa Malaysia and Chinese, with System and Dark appearance options.\n\nThe interface language is separate from the language the assistant replies in. It replies in whatever language you write to it in, so you can switch mid-conversation just by changing the language you type.'
		},
		{
			category: 'Settings',
			question: 'Some features I have seen elsewhere are missing. Why?',
			answer:
				'This is a deliberately focused version. Features that are not part of the current rollout — voice, notes, memory, chat folders, code execution and others — are switched off rather than left half-working.\n\nSome are planned for later releases. If something you need is missing, tell us through the feedback link below; that is what decides what gets built next.'
		}
	];

	let searchQuery = '';
	let selectedCategory = 'All';
	let openKey: string | null = null;

	const CATEGORIES = ['All', ...new Set(FAQS.map((f) => f.category))];

	const fill = (text: string, values: Record<string, string | number>) =>
		text.replace(/{{(\w+)}}/g, (match, key) => `${values[key] ?? match}`);

	$: resolved = FAQS.map((f) => ({
		...f,
		answer: fill(f.answer, {
			MAX_CHATS: maxChats,
			RETENTION_DAYS: retentionDays,
			MAX_FILE_COUNT: maxFileCount,
			MAX_FILE_SIZE: maxFileSize
		})
	}));

	$: query = searchQuery.trim().toLowerCase();

	$: filtered = resolved.filter((f) => {
		if (selectedCategory !== 'All' && f.category !== selectedCategory) {
			return false;
		}
		if (!query) {
			return true;
		}
		return f.question.toLowerCase().includes(query) || f.answer.toLowerCase().includes(query);
	});

	// Keyed on the question rather than the list index, so an open answer stays attached to its
	// own question when filtering reorders or shortens the list.
	const toggle = (key: string) => {
		openKey = openKey === key ? null : key;
	};

	const clearSearch = () => {
		searchQuery = '';
		selectedCategory = 'All';
		openKey = null;
	};
</script>

<Modal bind:show size="md">
	<div class="font-primary flex flex-col max-h-[85vh]">
		<div class="flex items-center justify-between px-5 pt-4 pb-1 shrink-0">
			<h2 class="text-lg font-medium text-gray-900 dark:text-gray-100">
				{$i18n.t('Help Center')}
			</h2>
			<button
				class="self-center p-1 rounded-full brand-nav-item transition"
				type="button"
				aria-label={$i18n.t('Close')}
				on:click={() => {
					show = false;
				}}
			>
				<XMark className="size-4" />
			</button>
		</div>

		<div class="px-5 pt-2 shrink-0">
			<div class="relative">
				<div class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 dark:text-gray-500">
					<Search className="size-4" />
				</div>
				<input
					class="w-full pl-9 pr-3 py-2 text-sm rounded-xl bg-gray-50 dark:bg-gray-850 text-gray-900 dark:text-gray-100 outline-hidden placeholder:text-gray-400 dark:placeholder:text-gray-500"
					placeholder={$i18n.t('Search help topics...')}
					aria-label={$i18n.t('Search help topics...')}
					bind:value={searchQuery}
				/>
			</div>
		</div>

		<div class="px-5 pt-3 pb-1 flex gap-1.5 overflow-x-auto shrink-0">
			{#each CATEGORIES as category (category)}
				<button
					type="button"
					class="px-2.5 py-1 rounded-full text-xs whitespace-nowrap transition {selectedCategory ===
					category
						? 'brand-btn-primary'
						: 'bg-gray-50 dark:bg-gray-850 text-gray-600 dark:text-gray-400 brand-nav-item'}"
					on:click={() => {
						selectedCategory = category;
						openKey = null;
					}}
				>
					{category}
				</button>
			{/each}
		</div>

		<div class="px-5 pb-2 overflow-y-auto grow">
			{#if filtered.length > 0}
				{#each filtered as faq (faq.question)}
					<div class="border-b border-gray-50 dark:border-gray-850 last:border-b-0">
						<button
							type="button"
							class="w-full flex items-start gap-2 text-left py-3"
							aria-expanded={openKey === faq.question}
							on:click={() => toggle(faq.question)}
						>
							<div class="grow">
								<div class="text-sm font-medium text-gray-900 dark:text-gray-100">
									{faq.question}
								</div>
								<div class="text-xs mt-0.5" style="color: var(--brand-primary)">
									{faq.category}
								</div>
							</div>
							<div
								class="shrink-0 mt-0.5 text-gray-400 dark:text-gray-500 transition-transform {openKey ===
								faq.question
									? 'rotate-180'
									: ''}"
							>
								<ChevronDown className="size-4" />
							</div>
						</button>

						{#if openKey === faq.question}
							<div
								class="text-sm text-gray-600 dark:text-gray-400 leading-relaxed rounded-xl bg-gray-50 dark:bg-gray-850 p-3 mb-3 whitespace-pre-line"
							>
								{faq.answer}
							</div>
						{/if}
					</div>
				{/each}
			{:else}
				<div class="py-10 text-center text-sm text-gray-500 dark:text-gray-400">
					<p>{$i18n.t('No results found.')}</p>
					<button
						type="button"
						class="mt-2 text-sm hover:underline"
						style="color: var(--brand-primary)"
						on:click={clearSearch}
					>
						{$i18n.t('Clear search')}
					</button>
				</div>
			{/if}
		</div>

		<div
			class="px-5 py-3 border-t border-gray-50 dark:border-gray-850 text-xs text-gray-500 dark:text-gray-400 text-center shrink-0"
		>
			{$i18n.t('Still need help or have a suggestion?')}
			<a
				href={SCHAT_FEEDBACK_URL}
				target="_blank"
				rel="noopener noreferrer"
				class="hover:underline font-medium"
				style="color: var(--brand-primary)"
			>
				{$i18n.t('Send feedback')}
			</a>
		</div>
	</div>
</Modal>
