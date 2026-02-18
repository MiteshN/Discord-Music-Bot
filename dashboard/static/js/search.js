/**
 * Search input + results dropdown.
 */
const Search = {
    debounceTimer: null,

    init() {
        const input = document.getElementById("search-input");
        const results = document.getElementById("search-results");

        input.addEventListener("input", () => {
            clearTimeout(this.debounceTimer);
            const q = input.value.trim();
            if (q.length < 2) {
                results.classList.remove("visible");
                return;
            }
            this.debounceTimer = setTimeout(() => this._search(q), 400);
        });

        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                const q = input.value.trim();
                if (q && App.guildId) {
                    API.addToQueue(App.guildId, q);
                    input.value = "";
                    results.classList.remove("visible");
                }
            }
            if (e.key === "Escape") {
                results.classList.remove("visible");
            }
        });

        // Close results on click outside
        document.addEventListener("click", (e) => {
            if (!e.target.closest(".search-container")) {
                results.classList.remove("visible");
            }
        });
    },

    async _search(query) {
        if (!App.guildId) return;
        const data = await API.search(App.guildId, query);
        if (!data || !data.length) {
            document.getElementById("search-results").classList.remove("visible");
            return;
        }
        this._renderResults(data);
    },

    _renderResults(results) {
        const container = document.getElementById("search-results");
        container.innerHTML = results.map((r, i) => `
            <div class="search-result-item" data-index="${i}">
                ${r.thumbnail
                    ? `<img class="search-result-thumb" src="${this._esc(r.thumbnail)}" alt="">`
                    : '<div class="search-result-thumb"></div>'}
                <div class="search-result-info">
                    <div class="search-result-title">${this._esc(r.title)}</div>
                    <div class="search-result-duration">${r.duration ? Player._formatTime(r.duration) : "Unknown"}</div>
                </div>
            </div>
        `).join("");

        container.querySelectorAll(".search-result-item").forEach((item, i) => {
            item.addEventListener("click", () => {
                const result = results[i];
                if (App.guildId) {
                    API.addToQueue(App.guildId, result.url || result.title);
                    document.getElementById("search-input").value = "";
                    container.classList.remove("visible");
                }
            });
        });

        container.classList.add("visible");
    },

    _esc(str) {
        const el = document.createElement("span");
        el.textContent = str || "";
        return el.innerHTML;
    },
};
