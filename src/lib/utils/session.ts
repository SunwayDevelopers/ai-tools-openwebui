import { userSignOut } from '$lib/apis/auths';
import { clearActiveTenant } from '$lib/apis/tenant';

/**
 * End the session and return where the caller should navigate next.
 *
 * Ordering matters. Under multi-tenancy `POST /api/v1/auths/signout` is a
 * tenant-scoped request, so the X-Tenant-Id header — injected from localStorage by
 * installTenantHeaderInjection() — must still be there when it goes out. Clearing
 * the active tenant first produced a 400 and left every cookie in place
 * (todo.md T1.4). So: call the API first, clear local state afterwards, and clear
 * it whether or not the call succeeded.
 *
 * Rejects if the server-side signout failed — but only *after* local state has
 * been cleared. Callers must surface that rather than swallowing it: the cookies
 * may have survived, which means the session is not actually dead.
 *
 * Note the zero-membership case does not depend on this ordering at all: those
 * users have no tenant to send. Reaching signout at all relies on
 * '/api/v1/auths/signout' being in _SYSTEM_EXACT_PATHS in
 * backend/open_webui/utils/tenant_middleware.py.
 */
export const endSession = async (): Promise<string> => {
	let res: { redirect_url?: string } | null = null;
	let error: unknown = null;

	try {
		res = await userSignOut();
	} catch (err) {
		error = err;
	}

	clearActiveTenant();
	try {
		localStorage.removeItem('token');
	} catch {
		/* ignore */
	}

	if (error) throw error;
	return res?.redirect_url ?? '/auth';
};
