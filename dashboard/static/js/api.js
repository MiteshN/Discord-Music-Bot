/**
 * Thin wrapper around the dashboard REST API. Errors are surfaced as toasts.
 */
const API = {
    async request(method, path, body) {
        const opts = { method, credentials: "same-origin", headers: {} };
        if (body !== undefined) {
            opts.headers["Content-Type"] = "application/json";
            opts.body = JSON.stringify(body);
        }
        let resp;
        try {
            resp = await fetch(path, opts);
        } catch {
            App.toast("Can't reach the dashboard. Is the bot running?", "error");
            return null;
        }
        if (resp.status === 401) {
            window.location.href = "/";
            return null;
        }
        let data = null;
        try { data = await resp.json(); } catch { /* empty body */ }
        if (!resp.ok || (data && data.error)) {
            App.toast((data && data.error) || `Request failed (${resp.status})`, "error");
            return null;
        }
        return data;
    },

    me() { return this.request("GET", "/api/@me"); },
    guilds() { return this.request("GET", "/api/guilds"); },

    /** POST an action for the selected guild, e.g. API.action("player/skip"). */
    action(path, body) {
        if (!App.guildId) return Promise.resolve(null);
        return this.request("POST", `/api/guild/${App.guildId}/${path}`, body);
    },

    removeFromQueue(index) {
        return this.request("DELETE", `/api/guild/${App.guildId}/queue/${index}`);
    },

    async search(query, signal) {
        const resp = await fetch(`/api/guild/${App.guildId}/search?q=${encodeURIComponent(query)}`,
            { credentials: "same-origin", signal });
        if (!resp.ok) return [];
        return resp.json();
    },
};
