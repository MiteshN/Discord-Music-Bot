/**
 * Search box: live YouTube results with keyboard navigation. Enter adds the typed text or link directly.
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
            const btn = e.target.closest("[data-top]");
            this._add(this.results[+row.dataset.index], !!btn);
        });

        document.addEventListener("click", (e) => { if (!e.target.closest("#search")) this._close(); });
    },

    async _search(query) {
        if (!App.guildId) return;
        this.controller?.abort();
        this.controller = new AbortController();
        this.wrap.classList.add("loading");
        try {
            this.results = await API.search(query, this.controller.signal);
            this._render();
        } catch (err) {
            if (err.name !== "AbortError") this._close();
        } finally {
            this.wrap.classList.remove("loading");
        }
    },

    _render() {
        this.active = -1;
        if (!this.results.length) {
            this._showHint("No results");
            return;
        }
        this.box.innerHTML = "";
        this.results.forEach((r, i) => {
            const row = document.createElement("div");
            row.className = "result";
            row.dataset.index = i;
            row.setAttribute("role", "option");
            row.innerHTML = `
                <img class="result-thumb" alt="" loading="lazy">
                <div class="result-info">
                    <div class="result-title"></div>
                    <div class="result-meta"></div>
                </div>
                <div class="result-actions">
                    <button class="result-btn" data-top title="Play next (Shift+Enter)"><span class="icon">vertical_align_top</span><span>Next</span></button>
                    <button class="result-btn primary" title="Add to queue (Enter)"><span class="icon">add</span><span>Add</span></button>
                </div>`;
            if (r.thumbnail) row.querySelector(".result-thumb").src = r.thumbnail;
            row.querySelector(".result-title").textContent = r.title;
            row.querySelector(".result-meta").textContent = r.duration ? fmt(r.duration) : "";
            this.box.append(row);
        });
        const hint = document.createElement("div");
        hint.className = "result-hint";
        hint.textContent = "↑↓ to choose · Enter to add · Shift+Enter to play next";
        this.box.append(hint);
        this.box.classList.add("open");
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

    _add(result, top) {
        this._addQuery(result.url || result.title, top);
    },

    async _addQuery(query, top) {
        this._close();
        this.input.value = "";
        App.toast(top ? "Adding to the top of the queue…" : "Adding…");
        const res = await API.action("queue/add", { query, top });
        if (res?.message) App.toast(res.message, "success");
    },

    _close() {
        this.box.classList.remove("open");
        this.results = [];
        this.active = -1;
    },
};
