/**
 * Search box: Spotify songs and albums plus YouTube videos, with keyboard navigation.
 * Enter with nothing highlighted adds the typed text or link directly.
 */
const Search = {
    timer: null,
    controller: null,
    results: [],
    active: -1,

    init() {
        this.wrap = document.getElementById("search");
        this.input = document.getElementById("search-input");
        this.box = document.getElementById("search-results");

        this.input.addEventListener("input", () => {
            clearTimeout(this.timer);
            const q = this.input.value.trim();
            if (q.length < 2 || /^https?:\/\//i.test(q)) {
                this._close();
                if (/^https?:\/\//i.test(q)) this._showHint("Press Enter to add this link");
                return;
            }
            this.timer = setTimeout(() => this._search(q), 300);
        });

        this.input.addEventListener("keydown", (e) => {
            if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                if (!this.results.length) return;
                e.preventDefault();
                const n = this.results.length;
                this.active = (this.active + (e.key === "ArrowDown" ? 1 : -1) + n) % n;
                this._highlight();
            } else if (e.key === "Enter") {
                e.preventDefault();
                if (this.active >= 0) this._add(this.results[this.active], e.shiftKey);
                else if (this.input.value.trim()) this._addQuery(this.input.value.trim(), e.shiftKey);
            } else if (e.key === "Escape") {
                this._close();
                this.input.blur();
            }
        });

        this.input.addEventListener("focus", () => { if (this.results.length) this.box.classList.add("open"); });

        this.box.addEventListener("mousedown", (e) => e.preventDefault()); // keep focus in the input
        this.box.addEventListener("click", (e) => {
            const row = e.target.closest(".result");
            if (!row) return;
            this._add(this.results[+row.dataset.index], !!e.target.closest("[data-top]"));
        });

        document.addEventListener("click", (e) => { if (!e.target.closest("#search")) this._close(); });
    },

    async _search(query) {
        if (!App.guildId) return;
        this.controller?.abort();
        this.controller = new AbortController();
        this.wrap.classList.add("loading");
        try {
            this._render(await API.search(query, this.controller.signal));
        } catch (err) {
            if (err.name !== "AbortError") this._close();
        } finally {
            this.wrap.classList.remove("loading");
        }
    },

    /** Flatten the grouped response into one navigable list. */
    _items(data) {
        const songs = (data.songs || []).map(s => ({
            kind: "song", source: "spotify", query: s.url, title: s.name,
            meta: [s.artist, s.duration ? fmt(s.duration) : ""], thumb: s.thumbnail, label: `${s.name} by ${s.artist}`,
        }));
        const albums = (data.albums || []).map(a => ({
            kind: "album", source: "spotify", query: a.url, title: a.title,
            meta: ["Album", a.artist, a.year, a.tracks ? `${a.tracks} songs` : ""], thumb: a.thumbnail, label: `album ${a.title}`,
        }));
        const videos = (data.videos || []).map(v => ({
            kind: "video", source: "youtube", query: v.url || v.title, title: v.title,
            meta: [v.duration ? fmt(v.duration) : ""], thumb: v.thumbnail, label: v.title,
        }));
        return [["Songs", songs], ["Albums", albums], ["Videos", videos]];
    },

    _render(data) {
        const groups = this._items(data || {});
        this.results = groups.flatMap(([, items]) => items);
        this.active = -1;
        if (!this.results.length) {
            this._showHint("No results");
            return;
        }

        this.box.innerHTML = "";
        let index = 0;
        for (const [heading, items] of groups) {
            if (!items.length) continue;
            const head = document.createElement("div");
            head.className = "result-group";
            head.textContent = heading;
            this.box.append(head);
            for (const item of items) this.box.append(this._row(item, index++));
        }
        const hint = document.createElement("div");
        hint.className = "result-hint";
        hint.textContent = "↑↓ to choose · Enter to add · Shift+Enter to play next";
        this.box.append(hint);
        this.box.classList.add("open");
    },

    _row(item, index) {
        const row = document.createElement("div");
        row.className = `result result-${item.kind}`;
        row.dataset.index = index;
        row.setAttribute("role", "option");
        row.innerHTML = `
            <img class="result-thumb" alt="" loading="lazy">
            <div class="result-info">
                <div class="result-title"></div>
                <div class="result-meta"><span class="src src-${item.source}">${item.source === "spotify" ? "Spotify" : "YouTube"}</span><span class="result-meta-text"></span></div>
            </div>
            <div class="result-actions">
                <button class="result-btn" data-top title="Play next (Shift+Enter)"><span class="icon">vertical_align_top</span><span>Next</span></button>
                <button class="result-btn primary" title="Add to queue (Enter)"><span class="icon">add</span><span>Add</span></button>
            </div>`;
        if (item.thumb) row.querySelector(".result-thumb").src = item.thumb;
        row.querySelector(".result-title").textContent = item.title;
        row.querySelector(".result-meta-text").textContent = item.meta.filter(Boolean).join(" · ");
        return row;
    },

    _highlight() {
        this.box.querySelectorAll(".result").forEach((row, i) => row.classList.toggle("active", i === this.active));
        this.box.querySelector(".result.active")?.scrollIntoView({ block: "nearest" });
    },

    _showHint(text) {
        this.results = [];
        this.box.innerHTML = "";
        const hint = document.createElement("div");
        hint.className = "result-hint";
        hint.textContent = text;
        this.box.append(hint);
        this.box.classList.add("open");
    },

    _add(item, top) {
        this._addQuery(item.query, top, item.label);
    },

    async _addQuery(query, top, label) {
        this._close();
        this.input.value = "";
        const what = label ? ` “${label}”` : "";
        App.toast(top ? `Adding${what} to play next…` : `Adding${what}…`);
        const res = await API.action("queue/add", { query, top });
        if (res?.message) App.toast(res.message, "success");
    },

    _close() {
        this.box.classList.remove("open");
        this.results = [];
        this.active = -1;
    },
};
