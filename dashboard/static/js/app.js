/**
 * Main app: auth check, guild selector (sidebar), page routing, queue toggle, toast system.
 */
const App = {
    guildId: null,
    guilds: [],
    currentPage: "home",
    queueOpen: true,
    menuOpen: false,

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

        // Navigation
        document.querySelectorAll(".nav-item").forEach(item => {
            item.addEventListener("click", () => {
                this._navigateTo(item.dataset.page);
            });
        });

        // Hamburger menu
        document.getElementById("hamburger-btn").addEventListener("click", () => {
            this._toggleMenu();
        });
        document.getElementById("sidebar-overlay").addEventListener("click", () => {
            this._toggleMenu(false);
        });

        // Queue toggle
        document.getElementById("btn-queue-toggle").addEventListener("click", () => {
            this._toggleQueue();
        });

        // Restore last guild from localStorage
        const lastGuild = localStorage.getItem("dashboard_guild");
        if (lastGuild && this.guilds.some(g => g.id === lastGuild)) {
            this._selectGuild(lastGuild);
        }

        // Restore queue panel state
        const queueState = localStorage.getItem("dashboard_queue_open");
        if (queueState === "false") {
            this.queueOpen = false;
            document.getElementById("queue-container").classList.add("collapsed");
        }

        // Settings: 24/7 toggle
        document.getElementById("setting-247").addEventListener("change", (e) => {
            if (this.guildId) {
                API.updateSettings(this.guildId, { twenty_four_seven: e.target.checked });
            }
        });
    },

    _populateGuilds() {
        const list = document.getElementById("guild-list");
        this.guilds.forEach(g => {
            const li = document.createElement("li");
            li.className = "guild-item";
            li.dataset.guildId = g.id;

            const icon = document.createElement("div");
            icon.className = "guild-icon";
            if (g.icon) {
                const img = document.createElement("img");
                img.src = g.icon;
                img.alt = "";
                icon.appendChild(img);
            } else {
                icon.textContent = g.name.charAt(0).toUpperCase();
            }

            const name = document.createElement("span");
            name.textContent = g.name;

            li.appendChild(icon);
            li.appendChild(name);
            li.addEventListener("click", () => this._selectGuild(g.id));
            list.appendChild(li);
        });
    },

    async _selectGuild(guildId) {
        if (!guildId) {
            this.guildId = null;
            WS.disconnect();
            document.getElementById("no-guild-msg").style.display = "flex";
            document.getElementById("page-home").style.display = "none";
            document.getElementById("page-settings").style.display = "none";
            this._clearGuildActive();
            return;
        }

        this.guildId = guildId;
        localStorage.setItem("dashboard_guild", guildId);

        // Update active state in sidebar
        this._clearGuildActive();
        const item = document.querySelector(`.guild-item[data-guild-id="${guildId}"]`);
        if (item) item.classList.add("active");

        // Show content
        document.getElementById("no-guild-msg").style.display = "none";
        this._navigateTo(this.currentPage);

        // Close mobile menu
        this._toggleMenu(false);

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

    _clearGuildActive() {
        document.querySelectorAll(".guild-item").forEach(el => el.classList.remove("active"));
    },

    _navigateTo(page) {
        this.currentPage = page;

        // Update nav active states
        document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));
        const navItem = document.querySelector(`.nav-item[data-page="${page}"]`);
        if (navItem) navItem.classList.add("active");

        // Show/hide pages
        document.querySelectorAll(".page").forEach(el => { el.style.display = "none"; });
        if (this.guildId) {
            const pageEl = document.getElementById(`page-${page}`);
            if (pageEl) pageEl.style.display = "flex";
        }
    },

    _toggleQueue(force) {
        const queue = document.getElementById("queue-container");
        this.queueOpen = force !== undefined ? force : !this.queueOpen;

        if (this.queueOpen) {
            queue.classList.remove("collapsed");
            queue.classList.add("open");
        } else {
            queue.classList.add("collapsed");
            queue.classList.remove("open");
        }
        localStorage.setItem("dashboard_queue_open", this.queueOpen);
    },

    _toggleMenu(force) {
        const menu = document.getElementById("menu-container");
        const overlay = document.getElementById("sidebar-overlay");
        this.menuOpen = force !== undefined ? force : !this.menuOpen;

        if (this.menuOpen) {
            menu.classList.add("open");
            overlay.classList.add("visible");
        } else {
            menu.classList.remove("open");
            overlay.classList.remove("visible");
        }
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
