import { describe, it, expect } from 'vitest';
import { deriveFirstName, getTimeOfDay, pickGreetingVariant } from './greeting';

describe('deriveFirstName', () => {
	it('title-cases an ALL-CAPS directory name', () => {
		expect(deriveFirstName('KHAIRUL BIN ABDULLAH')).toBe('Khairul');
	});

	it('keeps a normal first name', () => {
		expect(deriveFirstName('Zack Chong')).toBe('Zack');
	});

	it('lower-cases a shouted single name', () => {
		expect(deriveFirstName('ZACK')).toBe('Zack');
	});

	it('skips leading honorifics', () => {
		expect(deriveFirstName('Dr Tan Wei Ming')).toBe('Tan');
		expect(deriveFirstName('Haji Abdullah')).toBe('Abdullah');
		expect(deriveFirstName('Mr Zack Chong')).toBe('Zack');
	});

	it('keeps the common Chinese-Malaysian surname Tan rather than treating it as a title', () => {
		// "Tan" collides with the award title "Tan Sri" but is far more often a surname; we
		// must not strip it, or we mis-greet a huge slice of the userbase.
		expect(deriveFirstName('Tan Wei Ming')).toBe('Tan');
	});

	it('does not mangle internal capitals', () => {
		expect(deriveFirstName('McArthur Young')).toBe('McArthur');
		expect(deriveFirstName("O'Brien")).toBe("O'Brien");
	});

	it('returns null for email-like or handle values', () => {
		expect(deriveFirstName('khairul.abdullah@sunway.com')).toBeNull();
		expect(deriveFirstName('zack_chong')).toBeNull();
	});

	it('returns null when nothing usable remains', () => {
		expect(deriveFirstName('')).toBeNull();
		expect(deriveFirstName('   ')).toBeNull();
		expect(deriveFirstName(null)).toBeNull();
		expect(deriveFirstName(undefined)).toBeNull();
		expect(deriveFirstName('bin')).toBeNull();
		expect(deriveFirstName('x')).toBeNull();
		expect(deriveFirstName('123')).toBeNull();
	});
});

describe('getTimeOfDay', () => {
	const at = (h: number) => new Date(2026, 6, 21, h, 0, 0);

	it('splits the day into morning / afternoon / evening', () => {
		expect(getTimeOfDay(at(0))).toBe('morning');
		expect(getTimeOfDay(at(8))).toBe('morning');
		expect(getTimeOfDay(at(11))).toBe('morning');
		expect(getTimeOfDay(at(12))).toBe('afternoon');
		expect(getTimeOfDay(at(17))).toBe('afternoon');
		expect(getTimeOfDay(at(18))).toBe('evening');
		expect(getTimeOfDay(at(23))).toBe('evening');
	});
});

describe('pickGreetingVariant', () => {
	// `random` is called at most twice: once for the time-of-day share, once to index the pool.
	const stub = (...values: number[]) => {
		let i = 0;
		return () => values[Math.min(i++, values.length - 1)];
	};

	it('shows the time-of-day line for the lower half of the range', () => {
		expect(pickGreetingVariant(stub(0))).toBe('timeOfDay');
		expect(pickGreetingVariant(stub(0.49))).toBe('timeOfDay');
	});

	it('falls through to the neutral pool for the upper half', () => {
		expect(pickGreetingVariant(stub(0.5, 0))).toBe('welcomeBack');
		expect(pickGreetingVariant(stub(0.99, 0.5))).toBe('whatAreWeWorkingOn');
	});

	it('clamps a random() that returns exactly 1 instead of running off the pool', () => {
		expect(pickGreetingVariant(stub(1))).toBe('whatsOnYourMind');
	});

	it('reaches every variant over many rolls', () => {
		const seen = new Set(Array.from({ length: 2000 }, () => pickGreetingVariant()));
		expect(seen.size).toBe(7);
	});

	it('never repeats the previous variant', () => {
		const variants = [
			'timeOfDay',
			'welcomeBack',
			'readyWhenYouAre',
			'whatCanIHelpWith',
			'whatAreWeWorkingOn',
			'whereShouldWeStart',
			'whatsOnYourMind'
		] as const;

		for (const previous of variants) {
			for (let i = 0; i < 500; i++) {
				expect(pickGreetingVariant(Math.random, previous)).not.toBe(previous);
			}
		}
	});

	it('still reaches every other variant when one is excluded', () => {
		const seen = new Set(
			Array.from({ length: 2000 }, () => pickGreetingVariant(Math.random, 'timeOfDay'))
		);
		expect(seen.size).toBe(6);
		expect(seen.has('timeOfDay')).toBe(false);
	});

	it('consumes one random() for the time-of-day roll regardless of the exclusion', () => {
		// previous='timeOfDay' skips the time-of-day branch but must still burn the first draw,
		// so the pool index comes from the *second* value in both cases.
		expect(pickGreetingVariant(stub(0.9, 0), 'timeOfDay')).toBe('welcomeBack');
		expect(pickGreetingVariant(stub(0.9, 0), 'welcomeBack')).toBe('readyWhenYouAre');
	});
});
