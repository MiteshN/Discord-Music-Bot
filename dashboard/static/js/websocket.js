/**
 * WebSocket client: receives full player state and position updates, reconnects with backoff.
 */
const WS = {
    socket: null,
    guildId: null,
    retryTimer: null,
    retryDelay: 1000,

    connect(guildId) {
        this.disconnect();
        this.guildId = guildId;
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        const socket = new WebSocket(`${proto}//${location.host}/ws/${guildId}`);
        this.socket = socket;

        socket.onopen = () => {
            this.retryDelay = 1000;
            this._setStatus(true);
        };
        socket.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            if (msg.type === "state") App.onState(msg.data);
            else if (msg.type === "position") Player.syncPosition(msg.data);
        };
        socket.onclose = (event) => {
            this._setStatus(false);
            if (event.code === 4001) { window.location.href = "/"; return; }
            if (event.code === 4003) { App.toast("You don't have access to that server", "error"); return; }
            this._scheduleReconnect();
        };
        socket.onerror = () => socket.close();
    },

    disconnect() {
        clearTimeout(this.retryTimer);
        this.retryTimer = null;
        if (this.socket) {
            // Detach handlers first so a message still in flight from the old server can't repaint the page
            this.socket.onmessage = null;
            this.socket.onclose = null;
            this.socket.close();
            this.socket = null;
        }
        this._setStatus(false);
    },

    _scheduleReconnect() {
        if (!this.guildId) return;
        this.retryTimer = setTimeout(() => this.connect(this.guildId), this.retryDelay);
        this.retryDelay = Math.min(this.retryDelay * 2, 15000);
    },

    _setStatus(live) {
        const el = document.getElementById("ws-status");
        el.classList.toggle("live", live);
        el.title = live ? "Live" : "Reconnecting…";
    },
};

// Reconnect straight away when a backgrounded tab (e.g. on a phone) becomes visible again
document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && WS.guildId && (!WS.socket || WS.socket.readyState > 1)) {
        WS.connect(WS.guildId);
    }
});
