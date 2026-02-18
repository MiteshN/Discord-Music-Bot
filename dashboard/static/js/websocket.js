/**
 * WebSocket client with auto-reconnect and event dispatch.
 */
const WS = {
    socket: null,
    guildId: null,
    reconnectTimer: null,
    reconnectDelay: 1000,

    connect(guildId) {
        this.disconnect();
        this.guildId = guildId;

        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        const url = `${proto}//${location.host}/ws/${guildId}`;
        this.socket = new WebSocket(url);

        this.socket.onopen = () => {
            this.reconnectDelay = 1000;
            document.getElementById("ws-status").classList.add("connected");
            document.getElementById("ws-status").title = "Connected";
        };

        this.socket.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            this._dispatch(msg);
        };

        this.socket.onclose = () => {
            document.getElementById("ws-status").classList.remove("connected");
            document.getElementById("ws-status").title = "Disconnected";
            this._scheduleReconnect();
        };

        this.socket.onerror = () => {
            this.socket.close();
        };
    },

    disconnect() {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        if (this.socket) {
            this.socket.onclose = null;
            this.socket.close();
            this.socket = null;
        }
        document.getElementById("ws-status").classList.remove("connected");
    },

    _scheduleReconnect() {
        if (!this.guildId) return;
        this.reconnectTimer = setTimeout(() => {
            this.connect(this.guildId);
        }, this.reconnectDelay);
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
    },

    _dispatch(msg) {
        switch (msg.type) {
            case "full_state":
                Player.updateFull(msg.data);
                Queue.update(msg.data.queue);
                break;
            case "player_update":
                Player.updateFull(msg.data);
                break;
            case "heartbeat":
                Player.updatePosition(msg.data);
                break;
            case "volume_update":
                Player.updateVolume(msg.data.volume);
                break;
            case "loop_update":
                Player.updateLoop(msg.data.loop);
                break;
            case "queue_update":
                if (msg.data && msg.data.queue) {
                    Queue.update(msg.data.queue);
                } else {
                    // Refetch queue
                    API.getQueue(this.guildId).then(q => { if (q) Queue.update(q); });
                }
                break;
            case "disconnected":
                Player.showIdle();
                Queue.update([]);
                break;
        }
    },
};
