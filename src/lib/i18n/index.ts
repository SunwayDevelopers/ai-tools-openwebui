import i18next from 'i18next';
import resourcesToBackend from 'i18next-resources-to-backend';
import LanguageDetector from 'i18next-browser-languagedetector';
import type { i18n as i18nType } from 'i18next';
import { writable } from 'svelte/store';

const createI18nStore = (i18n: i18nType) => {
	const i18nWritable = writable(i18n);

	i18n.on('initialized', () => {
		i18nWritable.set(i18n);
	});
	i18n.on('loaded', () => {
		i18nWritable.set(i18n);
	});
	i18n.on('added', () => i18nWritable.set(i18n));
	i18n.on('languageChanged', (lang) => {
		i18nWritable.set(i18n);
		if (typeof document !== 'undefined') {
			document.documentElement.setAttribute('lang', lang);
		}
	});
	return i18nWritable;
};

const createIsLoadingStore = (i18n: i18nType) => {
	const isLoading = writable(false);

	// if loaded resources are empty || {}, set loading to true
	i18n.on('loaded', (resources) => {
		// console.log('loaded:', resources);
		isLoading.set(Object.keys(resources).length === 0);
	});

	// if resources failed loading, set loading to true
	i18n.on('failedLoading', () => {
		isLoading.set(true);
	});

	return isLoading;
};

// Sunway: the locales schat actually ships to users. The language PICKER is already
// narrowed to these three (ALLOWED_LANGUAGE_CODES in Settings/General.svelte), but that
// only filters the dropdown — LanguageDetector still reads `navigator`, and all ~60
// locale files are still in the bundle. So a browser reporting zh-TW, ja-JP or de-DE
// silently loaded THAT locale: a language the user was never offered, cannot see in the
// picker, and therefore cannot switch away from.
//
// It also broke the Sunway renames in a way that looked like a caching bug. en-US is
// upstream's SOURCE locale where 2407 of 2411 values are empty strings (the key IS the
// English text), and `returnEmptyString: false` makes an empty value fall through to the
// key. So "Workspace" -> "Knowledge Base" applied on en-GB but not on en-US, and Windows
// commonly reports en-US — same build, different label, depending on the browser.
//
// supportedLngs makes detection agree with the picker: anything outside this list falls
// back to en-GB, which is the deliberate house English (Malaysian business English is
// British-spelled). Fixing it here rather than by filling in en-US covers EVERY string,
// not one at a time, and keeps the change out of en-US/translation.json — a file upstream
// rewrites on most releases, so it would conflict on every sync.
const SUPPORTED_LOCALES = ['en-GB', 'ms-MY', 'zh-CN'];

export const initI18n = (defaultLocale?: string | undefined) => {
	const detectionOrder = defaultLocale
		? ['querystring', 'localStorage']
		: ['querystring', 'localStorage', 'navigator'];
	const fallbackDefaultLocale = defaultLocale ? [defaultLocale] : ['en-GB'];

	const loadResource = (language: string, namespace: string) =>
		import(`./locales/${language}/${namespace}.json`);

	i18next
		.use(resourcesToBackend(loadResource))
		.use(LanguageDetector)
		.init({
			debug: false,
			detection: {
				order: detectionOrder,
				caches: ['localStorage'],
				lookupQuerystring: 'lang',
				lookupLocalStorage: 'locale'
			},
			// Sunway: restricted to SUPPORTED_LOCALES — see the note above. A detected
			// language outside the list is rejected and fallbackLng applies, so an
			// en-US / zh-TW / de-DE browser lands on en-GB instead of a locale the
			// picker never offered. Dropping the `fr: ['fr-FR']` mapping with it:
			// neither code is supported any more, so it could never fire.
			supportedLngs: SUPPORTED_LOCALES,
			fallbackLng: {
				default: fallbackDefaultLocale
			},
			ns: 'translation',
			returnEmptyString: false,
			interpolation: {
				escapeValue: false // not needed for svelte as it escapes by default
			}
		});
};

const i18n = createI18nStore(i18next);
const isLoadingStore = createIsLoadingStore(i18next);

export const getLanguages = async () => {
	const languages = (await import(`./locales/languages.json`)).default;
	return languages;
};
export const changeLanguage = (lang: string) => {
	document.documentElement.setAttribute('lang', lang);
	i18next.changeLanguage(lang);
};

export default i18n;
export const isLoading = isLoadingStore;
