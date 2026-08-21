import { WEBUI_API_BASE_URL } from '$lib/constants';

export const getTools = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/tools/`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getToolList = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/tools/list`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

// Sunway: 13 of the 15 tool clients were deleted here (hardening plan Item 2, frontend half) --
// create, load-by-url, export, get/update/delete by id, access grants, and the six valve
// helpers. Their endpoints are gone: a "Tool" was Python source stored in a database row and
// exec()'d on the server, and the authoring routes that created those rows are deleted.
//
// getTools() and getToolList() remain. getTools() is how the Sdeck MCP server reaches a model
// (as `server:mcp:<id>`); tool SERVERS execute nothing inside schat.
