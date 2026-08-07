import { OPENAI_API_BASE_URL, WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';

export const getOpenAIConfig = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${OPENAI_API_BASE_URL}/config`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			if ('detail' in err) {
				error = err.detail;
			} else {
				error = 'Server connection failed';
			}
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

type OpenAIConfig = {
	ENABLE_OPENAI_API: boolean;
	OPENAI_API_BASE_URLS: string[];
	OPENAI_API_KEYS: string[];
	OPENAI_API_CONFIGS: object;
};

export const updateOpenAIConfig = async (token: string = '', config: OpenAIConfig) => {
	let error = null;

	const res = await fetch(`${OPENAI_API_BASE_URL}/config/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		},
		body: JSON.stringify({
			...config
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			if ('detail' in err) {
				error = err.detail;
			} else {
				error = 'Server connection failed';
			}
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getOpenAIModelsDirect = async (url: string, key: string) => {
	let error = null;

	const res = await fetch(`${url}/models`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(key && { authorization: `Bearer ${key}` })
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = `OpenAI: ${err?.error?.message ?? 'Network Problem'}`;
			return [];
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getOpenAIModels = async (token: string, urlIdx?: number) => {
	let error = null;

	const res = await fetch(
		`${OPENAI_API_BASE_URL}/models${typeof urlIdx === 'number' ? `/${urlIdx}` : ''}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				...(token && { authorization: `Bearer ${token}` })
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = `OpenAI: ${err?.error?.message ?? 'Network Problem'}`;
			return [];
		});

	if (error) {
		throw error;
	}

	return res;
};

export const verifyOpenAIConnection = async (
	token: string = '',
	connection: dict = {},
	direct: boolean = false
) => {
	const { url, key, config } = connection;
	if (!url) {
		throw 'OpenAI: URL is required';
	}

	let error = null;
	let res = null;

	if (direct) {
		res = await fetch(`${url}/models`, {
			method: 'GET',
			headers: {
				Accept: 'application/json',
				Authorization: `Bearer ${key}`,
				'Content-Type': 'application/json'
			}
		})
			.then(async (res) => {
				if (!res.ok) throw await res.json();
				return res.json();
			})
			.catch((err) => {
				error = `OpenAI: ${err?.error?.message ?? 'Network Problem'}`;
				return [];
			});

		if (error) {
			throw error;
		}
	} else {
		res = await fetch(`${OPENAI_API_BASE_URL}/verify`, {
			method: 'POST',
			headers: {
				Accept: 'application/json',
				Authorization: `Bearer ${token}`,
				'Content-Type': 'application/json'
			},
			body: JSON.stringify({
				url,
				key,
				config
			})
		})
			.then(async (res) => {
				if (!res.ok) throw await res.json();
				return res.json();
			})
			.catch((err) => {
				error = `OpenAI: ${err?.error?.message ?? 'Network Problem'}`;
				return [];
			});

		if (error) {
			throw error;
		}
	}

	return res;
};

export const chatCompletion = async (
	token: string = '',
	body: object,
	url: string = `${WEBUI_BASE_URL}/api`
): Promise<[Response | null, AbortController]> => {
	const controller = new AbortController();
	let error = null;

	const res = await fetch(`${url}/chat/completions`, {
		signal: controller.signal,
		method: 'POST',
		headers: {
			Authorization: `Bearer ${token}`,
			'Content-Type': 'application/json'
		},
		body: JSON.stringify(body)
	}).catch((err) => {
		console.error(err);
		// Sunway: same treatment as generateOpenAIChatCompletion below — a raw TypeError renders
		// in the chat as the bare string "Failed to fetch", which tells the user nothing. An
		// AbortError is the user pressing Stop, so it must keep its own identity.
		if (err instanceof TypeError) {
			error =
				'Could not reach SChat.ai as the connection was lost. This usually happens after the ' +
				'browser has been idle or the network changed. Refresh the page and try again.';
		} else {
			error = err;
		}
		return null;
	});

	if (error) {
		throw error;
	}

	return [res, controller];
};

// Sunway: turn a non-JSON HTTP error into something a user can act on. These come from the
// Istio gateway rather than from schat, so they carry no `detail` field to show.
//   502/503/504 -> no pod behind the gateway. Expected during every rollout (strategy Recreate,
//                  replicaCount 1), and during pod restarts. Resolves on its own.
//   504 also    -> upstream exceeded the route timeout (VirtualService apiTimeout).
// Not translated: this module has no i18n context, matching every other error string it throws.
// Move it into the calling component if these need to follow the user's language.
const describeNonJsonError = (status: number, raw: string): string => {
	if (status === 502 || status === 503) {
		return 'SChat.ai is restarting or temporarily unavailable. This usually clears within a minute so please try again shortly.';
	}
	if (status === 504) {
		return 'The request took too long and the gateway gave up. Try again, or shorten the request if it involved a large document.';
	}
	const snippet = (raw ?? '').trim().slice(0, 200);
	return `Server error ${status}${snippet ? `: ${snippet}` : ''}`;
};

export const generateOpenAIChatCompletion = async (
	token: string = '',
	body: object,
	url: string = `${WEBUI_BASE_URL}/api`
) => {
	let error = null;

	const res = await fetch(`${url}/chat/completions`, {
		method: 'POST',
		headers: {
			Authorization: `Bearer ${token}`,
			'Content-Type': 'application/json'
		},
		credentials: 'include',
		body: JSON.stringify(body)
	})
		.then(async (res) => {
			if (!res.ok) {
				// Sunway: was `throw await res.json()`. An Istio/Envoy gateway error answers with a
				// PLAIN-TEXT body ("no healthy upstream"), so res.json() threw a SyntaxError and the
				// user saw `Unexpected token 'o', "no healthy upstream" is not valid JSON` in the
				// chat. That is not an edge case: the chart deploys with strategy Recreate at
				// replicaCount 1 (RWO PVC + Alembic-on-boot), so EVERY rollout has a window with no
				// pod behind the gateway. Parse defensively and surface something actionable.
				const raw = await res.text();
				let parsed = null;
				try {
					parsed = JSON.parse(raw);
				} catch {
					// not JSON — a gateway/proxy error rather than an application one
				}
				if (parsed) throw parsed;
				throw { detail: describeNonJsonError(res.status, raw) };
			}
			return res.json();
		})
		.catch((err) => {
			// fetch() itself rejects with a TypeError ("Failed to fetch") when the request never
			// got a response at all — laptop sleep, network change, VPN drop, connection reset
			// mid-request. Reported by users as "left it open, came back, failed to fetch".
			if (err instanceof TypeError) {
				error =
					'Could not reach schat — the connection was lost. This usually happens after the ' +
					'browser has been idle or the network changed. Refresh the page and try again.';
			} else {
				error = err?.detail ?? err;
			}
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const synthesizeOpenAISpeech = async (
	token: string = '',
	speaker: string = 'alloy',
	text: string = '',
	model: string = 'tts-1'
) => {
	let error = null;

	const res = await fetch(`${OPENAI_API_BASE_URL}/audio/speech`, {
		method: 'POST',
		headers: {
			Authorization: `Bearer ${token}`,
			'Content-Type': 'application/json'
		},
		body: JSON.stringify({
			model: model,
			input: text,
			voice: speaker
		})
	}).catch((err) => {
		console.error(err);
		error = err;
		return null;
	});

	if (error) {
		throw error;
	}

	return res;
};
