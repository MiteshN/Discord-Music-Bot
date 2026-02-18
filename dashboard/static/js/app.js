/**
 * Main app: auth check, guild selector, routing, toast system.
 */
const App = {
    guildId: null,
    guilds: [],

    async init() {
        // Check auth
        const me = await API.getMe();
        if (!me) return;
        document.getElementById("user-info").textContent = me.username;

        // Load guilds
        this.guilds = await API.getGuilds() || [];
        this._populateGuilds();

        // Init components
        Player.init();
        Queue.init();
        Search.init();

        // Guild selector
        document.getElementById("guild-select").addEventListener("change", (e) => {
            this._selectGuild(e.target.value);
        });

        // Restore last guild from localStorage
        const lastGuild = localStorage.getItem("dashboard_guild");
        if (lastGuild && this.guilds.some(g => g.id === lastGuild)) {
            document.getElementById("guild-select").value = lastGuild;
            this._selectGuild(lastGuild);
        }

        // Settings: 24/7 toggle
        document.getElementById("setting-247").addEventListener("change", (e) => {
            if (this.guildId) {
                API.updateSettings(this.guildId, { twenty_four_seven: e.target.checked });
            }
        });
    },

    _populateGuilds() {
        const select = document.getElementById("guild-select");
        this.guilds.forEach(g => {
            const opt = document.createElement("option");
            opt.value = g.id;
            opt.textContent = g.name;
            select.appendChild(opt);
        });
    },

    async _selectGuild(guildId) {
        if (!guildId) {
            this.guildId = null;
            WS.disconnect();
            document.getElementById("no-guild-msg").style.display = "flex";
            document.getElementById("player-section").style.display = "none";
            return;
        }

        this.guildId = guildId;
        localStorage.setItem("dashboard_guild", guildId);
        document.getElementById("no-guild-msg").style.display = "none";
        document.getElementById("player-section").style.display = "block";

        // Load initial state
        const [player, queue, settings] = await Promise.all([
            API.getPlayer(guildId),
            API.getQueue(guildId),
            API.getSettings(guildId),
        ]);

        if (player) Player.updateFull(player);
        if (queue) Queue.update(queue);
        if (settings) {
            document.getElementById("setting-247").checked = settings.twenty_four_seven;
        }

        // Connect WebSocket
        WS.connect(guildId);
    },

    toast(message, type = "info") {
        const container = document.getElementById("toast-container");
        const toast = document.createElement("div");
        toast.className = `toast ${type}`;
        toast.textContent = message;
        container.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = "0";
            toast.style.transition = "opacity 0.3s";
            setTimeout(() => toast.remove(), 300);
        }, 4000);
    },
};

// Boot
document.addEventListener("DOMContentLoaded", () => App.init());
