import { WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';

// Multi-tenancy: the active business-unit slug travels as X-Tenant-Id on every
// data-plane request to schat. The active slug is kept in localStorage and
// injected globally by installTenantHeaderInjection() (see below).
const ACTIVE_TENANT_KEY = 'activeTenant';

export const getActiveTenant = (): string | null => {
	try {
		return localStorage.getItem(ACTIVE_TENANT_KEY);
	} catch {
		return null;
	}
};

export const setActiveTenant = (slug: string): void => {
	try {
		localStorage.setItem(ACTIVE_TENANT_KEY, slug);
	} catch {
		/* ignore */
	}
};

export const clearActiveTenant = (): void => {
	try {
		localStorage.removeItem(ACTIVE_TENANT_KEY);
	} catch {
		/* ignore */
	}
};

export type WhoAmI = {
	identity: { email: string; name?: string | null } | null;
	tenants: { slug: string; role: string; name?: string | null }[];
};

// Thrown by the workspace gate so callers can tell "you are not authenticated"
// apart from "IAM is having a bad day". The previous code threw the parsed
// response body, which discarded the status — leaving the only possible reaction
// to any failure at all be to destroy the session (todo.md T1.5).
export class TenantGateError extends Error {
	status: number;
	detail?: string;

	// status 0 = the request never got a response (offline, DNS, connection reset).
	constructor(status: number, detail?: string) {
		super(detail || `HTTP ${status}`);
		this.name = 'TenantGateError';
		this.status = status;
		this.detail = detail;
	}

	// Could this plausibly succeed if we just asked again? 401/403 are *answers*,
	// not failures, so they are deliberately excluded: retrying them is pointless
	// and signing out on them is the correct response.
	get isTransient(): boolean {
		return this.status === 0 || this.status === 408 || this.status === 429 || this.status >= 500;
	}
}

// GET /api/v1/tenant/me — the pre-tenant bootstrap for the workspace gate. Reads
// the httpOnly iam_token cookie (sent automatically), so it needs no bearer and
// no X-Tenant-Id. Empty `tenants` ⇒ the caller must block access.
export const getMyTenants = async (): Promise<WhoAmI> => {
	let res: Response;
	try {
		res = await fetch(`${WEBUI_API_BASE_URL}/tenant/me`, {
			method: 'GET',
			headers: { 'Content-Type': 'application/json' },
			credentials: 'include'
		});
	} catch (err) {
		throw new TenantGateError(0, (err as Error)?.message || 'network error');
	}
	if (!res.ok) {
		const body = await res.json().catch(() => null);
		throw new TenantGateError(res.status, body?.detail);
	}
	return res.json();
};

const GATE_RETRY_DELAYS_MS = [400, 1200];

// getMyTenants() with a bounded retry, for the boot-time workspace gate. An IAM
// pod restart or a momentary blip should not be able to sign anyone out, so
// transient failures are retried before the caller has to decide anything. Worst
// case this adds ~1.6s of backoff on top of the failed attempts themselves.
export const getMyTenantsWithRetry = async (): Promise<WhoAmI> => {
	for (let attempt = 0; ; attempt++) {
		try {
			return await getMyTenants();
		} catch (err) {
			if (!(err instanceof TenantGateError && err.isTransient)) throw err;
			if (attempt >= GATE_RETRY_DELAYS_MS.length) throw err;
			await new Promise((resolve) => setTimeout(resolve, GATE_RETRY_DELAYS_MS[attempt]));
		}
	}
};

// ---------------------------------------------------------------------------
// Session refresh
// ---------------------------------------------------------------------------

// The IAM access token is short-lived (~5 min) and lives in an httpOnly cookie the SPA
// cannot read, so the only way to know it expired is to be told: a 401 from the tenant
// middleware. POST /api/v1/tenant/refresh swaps it for a fresh one server-side; no token
// material passes through JS in either direction.
const REFRESH_PATH = '/api/v1/tenant/refresh';

// Paths that must NEVER trigger a refresh attempt: refresh itself (infinite recursion),
// and the endpoints whose whole job is to end or begin a session.
const NO_REFRESH_PATHS = [REFRESH_PATH, '/api/v1/auths/signout', '/api/v1/auths/signin', '/oauth'];

// Single-flight. A page load fires many parallel requests, so an expiring token produces
// a burst of simultaneous 401s. Letting each one refresh independently would rotate the
// token N times concurrently — and since rotation is single-use, the losers would present
// an already-spent token and trip IAM's replay detection, which revokes *every* session.
// One in-flight promise, shared by all waiters, is what keeps that from happening.
let refreshInFlight: Promise<boolean> | null = null;
let proactiveTimer: ReturnType<typeof setTimeout> | null = null;

const doRefresh = async (): Promise<boolean> => {
	let res: Response;
	try {
		res = await fetch(`${WEBUI_BASE_URL || ''}${REFRESH_PATH}`, {
			method: 'POST',
			credentials: 'include'
		});
	} catch {
		return false; // offline / connection reset — transient, keep the session
	}
	if (!res.ok) return false;
	try {
		const body = await res.json();
		// Chain the next proactive refresh off this one's lifetime.
		if (typeof body?.expires_in === 'number') scheduleProactiveRefresh(body.expires_in);
	} catch {
		/* body is advisory only; the cookies are already set */
	}
	return true;
};

export const refreshSession = (): Promise<boolean> => {
	if (!refreshInFlight) {
		refreshInFlight = doRefresh().finally(() => {
			refreshInFlight = null;
		});
	}
	return refreshInFlight;
};

// Refresh a little before expiry so an idle tab does not have to fail a request first.
// Belt-and-braces only — the reactive path below is what guarantees correctness.
export const scheduleProactiveRefresh = (expiresInSeconds: number): void => {
	if (typeof window === 'undefined') return;
	if (proactiveTimer) clearTimeout(proactiveTimer);
	// 80% of the lifetime, floored so a misconfigured tiny TTL cannot spin.
	const delay = Math.max(30_000, Math.floor(expiresInSeconds * 0.8 * 1000));
	proactiveTimer = setTimeout(() => {
		refreshSession();
	}, delay);
};

// Refresh failed. Distinguish "the session is definitively over" from "IAM is unwell":
// only the former should destroy the UI session. A transient 5xx that logged everyone out
// is exactly the bug T1.5 describes, so anything non-definitive is left to the caller to
// surface as a retriable error.
const onRefreshFailed = (originalResponse: Response): void => {
	if (typeof window === 'undefined') return;
	if (window.location.pathname.startsWith('/auth')) return;
	// 401 on the original request + a refresh that could not renew it ⇒ signed out.
	// Land on /auth loudly rather than leaving a UI that looks signed in but 401s on
	// every call (todo.md T1.2).
	if (originalResponse.status === 401) {
		clearActiveTenant();
		window.location.href = '/auth';
	}
};

// Install a one-time global fetch wrapper that (a) stamps X-Tenant-Id onto every
// same-origin request to schat when an active tenant is selected, and (b) transparently
// renews an expired IAM session on 401 and replays the request. This makes the whole
// existing API layer tenant-aware and refresh-aware without touching each call site.
// Safe: it only touches same-origin schat requests and never overwrites an explicit
// header. Idempotent — a guard flag prevents double-wrapping on HMR/remount.
export const installTenantHeaderInjection = (): void => {
	if (typeof window === 'undefined') return;
	if ((window as any).__tenantFetchPatched) return;
	(window as any).__tenantFetchPatched = true;

	const origin = window.location.origin;
	const apiBase = WEBUI_BASE_URL || origin; // dev points at :8080; prod is same-origin
	const nativeFetch = window.fetch.bind(window);

	const isSchatRequest = (url: string): boolean => {
		if (url.startsWith('/')) return true; // relative → same origin
		return url.startsWith(origin) || (!!apiBase && url.startsWith(apiBase));
	};

	const pathOf = (url: string): string => {
		try {
			return new URL(url, origin).pathname;
		} catch {
			return url;
		}
	};

	const mayRefresh = (url: string): boolean => {
		const path = pathOf(url);
		return !NO_REFRESH_PATHS.some((p) => path.startsWith(p));
	};

	window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
		let patched: RequestInit | undefined = init;
		// Non-null only when this request is eligible for a refresh-and-retry.
		let replay: (() => Promise<Response>) | null = null;

		try {
			const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
			const slug = getActiveTenant();
			if (slug && url && isSchatRequest(url)) {
				const headers = new Headers(init?.headers || (input instanceof Request ? input.headers : undefined));
				if (!headers.has('X-Tenant-Id')) headers.set('X-Tenant-Id', slug);
				patched = { ...init, headers };
			}
			if (url && isSchatRequest(url) && mayRefresh(url)) {
				// A Request's body is a one-shot stream, so the retry copy must be taken
				// BEFORE the first send or it would go out with an empty body. If cloning
				// throws (body already consumed) we land in the catch and simply do not
				// retry — better than replaying a broken request.
				const spare = input instanceof Request ? input.clone() : null;
				replay = () => nativeFetch((spare ?? input) as any, patched);
			}
		} catch {
			/* fall through: unmodified fetch, no retry */
		}

		const res = await nativeFetch(input as any, patched);
		if (res.status !== 401 || !replay) return res;
		if (!(await refreshSession())) {
			onRefreshFailed(res);
			return res;
		}
		return replay();
	};
};

const tenantHeaders = (token: string, tenantId?: string | null) => {
	const slug = tenantId ?? getActiveTenant();
	const headers: Record<string, string> = {
		'Content-Type': 'application/json',
		Authorization: `Bearer ${token}`
	};
	if (slug) headers['X-Tenant-Id'] = slug;
	return headers;
};

export type TenantMember = {
	id: string;
	// IAM identifies members by email (the entitlement key); no WorkOS user id.
	email: string;
	role: string;
	status?: string | null;
};

export type BulkAddResultItem = {
	email: string;
	status: 'added' | 'already_member' | 'invalid' | 'duplicate' | 'error';
	detail?: string;
};

export type BulkAddResult = {
	added: number;
	total: number;
	results: BulkAddResultItem[];
};

export const listTenantMembers = async (
	token: string,
	tenantId?: string | null
): Promise<TenantMember[]> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/tenant/members/`, {
		method: 'GET',
		headers: tenantHeaders(token, tenantId)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			error = err.detail ?? err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const bulkAddTenantMembers = async (
	token: string,
	emails: string[],
	role: string = 'user',
	tenantId?: string | null
): Promise<BulkAddResult> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/tenant/members/bulk`, {
		method: 'POST',
		headers: tenantHeaders(token, tenantId),
		body: JSON.stringify({ emails, role })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			error = err.detail ?? err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const updateTenantMemberRole = async (
	token: string,
	email: string,
	role: string,
	tenantId?: string | null
): Promise<TenantMember> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/tenant/members/${encodeURIComponent(email)}`, {
		method: 'PATCH',
		headers: tenantHeaders(token, tenantId),
		body: JSON.stringify({ role })
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			error = err.detail ?? err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const removeTenantMember = async (
	token: string,
	email: string,
	tenantId?: string | null
): Promise<boolean> => {
	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/tenant/members/${encodeURIComponent(email)}`, {
		method: 'DELETE',
		headers: tenantHeaders(token, tenantId)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			error = err.detail ?? err;
			return null;
		});

	if (error) throw error;
	return res;
};
