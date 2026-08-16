import { WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';
import type { Banner } from '$lib/types';

export const getModelsDefaults = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/models/defaults`, {
		method: 'GET',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getBanners = async (token: string): Promise<Banner[]> => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/configs/banners`, {
		method: 'GET',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

// Sunway: NOT an endpoint call -- it builds the OAuth authorize URL that the composer and the
// integrations menu link to. It survived the Item 7 deletion because there is no request here to
// delete; /oauth/clients/{id}/authorize is the login redirect flow, not admin configuration.
export const getOAuthClientAuthorizationUrl = (clientId: string, type: null | string = null) => {
	const oauthClientId = type ? `${type}:${clientId}` : clientId;
	return `${WEBUI_BASE_URL}/oauth/clients/${oauthClientId}/authorize`;
};

// Sunway: 17 of the 20 clients here were deleted (hardening plan Item 7). Their endpoints --
// the whole admin surface of routers/configs.py -- are gone: configuration now comes from the
// chart, and app.state.config is process-global, so a write by one tenant's admin reached every
// tenant on the pod.
//
// getModelsDefaults() and getBanners() remain: both are get_verified_user reads that the app
// itself uses, not admin configuration.
