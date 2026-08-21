// i18next-parser.config.ts
// Sunway: catalogs are generated for the locales schat actually ships, not all ~60.
// Upstream mapped `locales` over the whole of languages.json, so every new string landed
// as an empty key in ~60 files and each i18n:parse produced a diff nobody could review or
// translate. SUPPORTED_LOCALES is the same list i18next detection and the Settings
// language picker use (src/lib/i18n/index.ts). The other locale files are untouched, not
// deleted — restoring one means adding its code there.
import { SUPPORTED_LOCALES } from './src/lib/i18n/index.ts';

export default {
	contextSeparator: '_',
	createOldCatalogs: false,
	defaultNamespace: 'translation',
	defaultValue: '',
	indentation: 2,
	keepRemoved: false,
	keySeparator: false,
	lexers: {
		svelte: ['JavascriptLexer'],
		js: ['JavascriptLexer'],
		ts: ['JavascriptLexer'],

		default: ['JavascriptLexer']
	},
	lineEnding: 'auto',
	locales: SUPPORTED_LOCALES,
	namespaceSeparator: false,
	output: 'src/lib/i18n/locales/$LOCALE/$NAMESPACE.json',
	pluralSeparator: '_',
	input: 'src/**/*.{js,svelte}',
	sort: true,
	verbose: true,
	failOnWarnings: false,
	failOnUpdate: false,
	customValueTemplate: null,
	resetDefaultValueLocale: null,
	i18nextOptions: null,
	yamlOptions: null
};
