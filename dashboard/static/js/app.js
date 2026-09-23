/**
 * App shell: user + server rail, server selection, mobile tabs, keyboard shortcuts, toasts.
 */
const App = {
    guildId: null,
    guilds: [],

    async init() {
        Player.init();
        Queue.init();
        Search.init();

        const me = await API.me();
        if (!me) return;
        const avatar = document.getElementById("user-avatar");
        avatar.title = `${me.username} · Log out`;
        if (me.avatar) avatar.style.backgroundImage = `url(https://cdn.discordapp.com/avatars/${me.id}/${me.avatar}.png?size=80)`;

        this.guilds = (await API.guilds()) || [];
        this._renderGuilds();

        document.querySelectorAll("#tabs .tab").forEach(tab =>
            tab.addEventListener("click", () => this._setTab(tab.dataset.tab)));
        this._setTab("player");

        document.addEventListener("keydown", (e) => this._shortcut(e));

        let saved = null;
        try { saved = localStorage.getItem("mugetsu.guild"); } catch { /* storage unavailable */ }
        const initial = this.guilds.find(g => g.id === saved) || this.guilds.find(g => g.playing)
            || (this.guilds.length === 1 ? this.guilds[0] : null);
        if (initial) this.selectGuild(initial.id);
        else if (!this.guilds.length) {
            document.querySelector("#no-guild h2").textContent = "No shared servers";
            document.querySelector("#no-guild p").textContent = "You aren't in any server this bot is in yet.";
        }
    },

    _renderGuilds() {
        const list = document.getElementById("guild-list");
        list.replaceChildren(...this.guilds.map(g => {
            const btn = document.createElement("button");
            btn.className = "guild" + (g.playing ? " playing" : "");
            btn.dataset.guildId = g.id;
            btn.setAttribute("aria-label", g.name);
            if (g.icon) {
                const img = document.createElement("img");
                img.src = g.icon;
                img.alt = "";
                btn.append(img);
            } else {
                btn.append(g.name.split(/\s+/).map(w => w[0]).join("").slice(0, 3));
            }
            const live = document.createElement("span");
            live.className = "guild-live";
            const tip = document.createElement("span");
            tip.className = "guild-tip";
            tip.textContent = g.name;
            btn.append(live, tip);
            btn.addEventListener("click", () => this.selectGuild(g.id));
            return btn;
        }));
    },

    selectGuild(guildId) {
        if (guildId === this.guildId) return;
        this.guildId = guildId;
        try { localStorage.setItem("mugetsu.guild", guildId); } catch { /* storage unavailable */ }

        const guild = this.guilds.find(g => g.id === guildId);
        document.getElementById("guild-name").textContent = guild ? guild.name : "Mugetsu";
        document.getElementById("voice-channel").textContent = "Connecting…";
        document.querySelectorAll(".guild").forEach(el => el.classList.toggle("active", el.dataset.guildId === guildId));

        document.getElementById("no-guild").hidden = true;
        document.getElementById("player").hidden = false;
        document.getElementById("queue").hidden = false;
        document.getElementById("tabs").hidden = false;

        Player.reset();
        Queue.signature = "";
        WS.connect(guildId);
    },

    onState(s) {
        Player.render(s);
        Queue.render(s);
        document.getElementById("voice-channel").textContent = s.in_voice
            ? `Connected to ${s.channel}` : "Not in a voice channel";
        const railItem = document.querySelector(`.guild[data-guild-id="${this.guildId}"]`);
        railItem?.classList.toggle("playing", !!s.current && s.in_voice);
    },

    _setTab(tab) {
        document.getElementById("stage").dataset.tab = tab;
        document.querySelectorAll("#tabs .tab").forEach(t => t.classList.toggle("active", t.dataset.tab === tab));
    },

    _shortcut(e) {
        const typing = e.target.closest("input, textarea, select") && e.target.type !== "range";
        if (e.key === "/" && !typing) {
            e.preventDefault();
            document.getElementById("search-input").focus();
            return;
        }
        if (typing || e.ctrlKey || e.metaKey || e.altKey || !this.guildId) return;
        if (e.code === "Space") {
            e.preventDefault();
            document.getElementById("btn-play").click();
        } else if (e.shiftKey && e.key === "ArrowRight") {
            document.getElementById("btn-skip").click();
        } else if (e.shiftKey && e.key === "ArrowLeft") {
            document.getElementById("btn-prev").click();
        }
    },

    toast(message, type = "info") {
        const icons = { info: "info", success: "check_circle", error: "error" };
        const container = document.getElementById("toasts");
        const toast = document.createElement("div");
        toast.className = `toast ${type}`;
        const icon = document.createElement("span");
        icon.className = "icon filled";
        icon.textContent = icons[type] || "info";
        toast.append(icon, message);
        container.append(toast);
        while (container.children.length > 3) container.firstChild.remove();
        setTimeout(() => {
            toast.classList.add("leaving");
            setTimeout(() => toast.remove(), 300);
        }, type === "error" ? 5000 : 3000);
    },
};

document.addEventListener("DOMContentLoaded", () => App.init());
