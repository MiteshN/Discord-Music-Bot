/**
 * API wrapper for dashboard REST endpoints.
 */
const API = {
    async request(method, path, body) {
        const opts = {
            method,
            credentials: "same-origin",
            headers: {},
        };
        if (body !== undefined) {
            opts.headers["Content-Type"] = "application/json";
            opts.body = JSON.stringify(body);
        }
        const resp = await fetch(path, opts);
        if (resp.status === 401) {
            window.location.href = "/login";
            return null;
        }
        const data = await resp.json();
        if (data.error) {
            App.toast(data.error, "error");
            return null;
        }
        return data;
    },

    getMe() {
        return this.request("GET", "/api/@me");
    },

    getGuilds() {
        return this.request("GET", "/api/guilds");
    },

    getPlayer(guildId) {
        return this.request("GET", `/api/guild/${guildId}/player`);
    },

    getQueue(guildId) {
        return this.request("GET", `/api/guild/${guildId}/queue`);
    },

    getSettings(guildId) {
        return this.request("GET", `/api/guild/${guildId}/settings`);
    },

    pauseResume(guildId) {
        return this.request("POST", `/api/guild/${guildId}/player/pause`);
    },

    skip(guildId) {
        return this.request("POST", `/api/guild/${guildId}/player/skip`);
    },

    stop(guildId) {
        return this.request("POST", `/api/guild/${guildId}/player/stop`);
    },

    seek(guildId, position) {
        return this.request("POST", `/api/guild/${guildId}/player/seek`, { position });
    },

    setVolume(guildId, volume) {
        return this.request("POST", `/api/guild/${guildId}/player/volume`, { volume });
    },

    setLoop(guildId, mode) {
        return this.request("POST", `/api/guild/${guildId}/player/loop`, { mode });
    },

    setFilter(guildId, filter) {
        return this.request("POST", `/api/guild/${guildId}/player/filter`, { filter });
    },

    addToQueue(guildId, query) {
        return this.request("POST", `/api/guild/${guildId}/queue/add`, { query });
    },

    addToQueueTop(guildId, query) {
        return this.request("POST", `/api/guild/${guildId}/queue/add-top`, { query });
    },

    moveInQueue(guildId, from, to) {
        return this.request("POST", `/api/guild/${guildId}/queue/move`, { from, to });
    },

    shuffleQueue(guildId) {
        return this.request("POST", `/api/guild/${guildId}/queue/shuffle`);
    },

    removeFromQueue(guildId, index) {
        return this.request("DELETE", `/api/guild/${guildId}/queue/${index}`);
    },

    search(guildId, query) {
        return this.request("GET", `/api/guild/${guildId}/search?q=${encodeURIComponent(query)}`);
    },

    updateSettings(guildId, settings) {
        return this.request("POST", `/api/guild/${guildId}/settings`, settings);
    },
};
