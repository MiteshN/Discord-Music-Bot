/**
 * Queue panel UI with "Now Playing" section, queue list, remove and drag-and-drop reorder.
 */
const Queue = {
    items: [],

    init() {
        document.getElementById("btn-shuffle-queue").addEventListener("click", () => {
            if (App.guildId) API.shuffleQueue(App.guildId);
        });
    },

    update(queue) {
        this.items = queue || [];
        this._render();
    },

    updateNowPlaying(song) {
        const section = document.getElementById("queue-now-playing");
        const container = document.getElementById("queue-current");

        if (!song) {
            section.style.display = "none";
            return;
        }

        section.style.display = "block";
        container.innerHTML = `
            ${song.thumbnail
                ? `<img class="queue-current-thumb" src="${this._esc(song.thumbnail)}" alt="">`
                : '<div class="queue-current-thumb"></div>'}
            <div class="queue-current-info">
                <div class="queue-current-title">${this._esc(song.title)}</div>
                <div class="queue-current-meta">
                    ${song.duration ? Player._formatTime(song.duration) : "Live"} &middot; ${this._esc(song.requester)}
                </div>
            </div>
        `;
    },

    _render() {
        const list = document.getElementById("queue-list");
        const countEl = document.getElementById("queue-count");

        if (!this.items.length) {
            list.innerHTML = '<li class="queue-empty">Queue is empty</li>';
            countEl.textContent = "";
            return;
        }

        countEl.textContent = `(${this.items.length})`;

        list.innerHTML = this.items.map((song, i) => {
            const thumb = song.thumbnail || this._ytThumb(song.url);
            const duration = song.duration ? Player._formatTime(song.duration) : "Queued";
            return `
            <li class="queue-item" draggable="true" data-index="${i}">
                <span class="queue-item-index">${i + 1}</span>
                ${thumb
                    ? `<img class="queue-item-thumb" src="${this._esc(thumb)}" alt="">`
                    : '<div class="queue-item-thumb"></div>'}
                <div class="queue-item-info">
                    <div class="queue-item-title">${this._esc(song.title)}</div>
                    <div class="queue-item-meta">
                        ${duration} &middot; ${this._esc(song.requester)}
                    </div>
                </div>
                <div class="queue-item-actions">
                    <button class="queue-item-btn" data-remove="${i}" title="Remove">
                        <span class="material-symbols-outlined">close</span>
                    </button>
                </div>
            </li>`;
        }).join("");

        // Remove buttons
        list.querySelectorAll("[data-remove]").forEach(btn => {
            btn.addEventListener("click", (e) => {
                e.stopPropagation();
                const idx = parseInt(btn.dataset.remove);
                if (App.guildId) API.removeFromQueue(App.guildId, idx);
            });
        });

        // Drag and drop
        let dragIdx = null;
        list.querySelectorAll(".queue-item").forEach(item => {
            item.addEventListener("dragstart", (e) => {
                dragIdx = parseInt(item.dataset.index);
                item.classList.add("dragging");
                e.dataTransfer.effectAllowed = "move";
            });
            item.addEventListener("dragend", () => {
                item.classList.remove("dragging");
                dragIdx = null;
            });
            item.addEventListener("dragover", (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = "move";
            });
            item.addEventListener("drop", (e) => {
                e.preventDefault();
                const toIdx = parseInt(item.dataset.index);
                if (dragIdx !== null && dragIdx !== toIdx && App.guildId) {
                    API.moveInQueue(App.guildId, dragIdx, toIdx);
                }
            });
        });
    },

    _ytThumb(url) {
        if (!url) return null;
        const m = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([A-Za-z0-9_-]{11})/);
        return m ? `https://i.ytimg.com/vi/${m[1]}/mqdefault.jpg` : null;
    },

    _esc(str) {
        const el = document.createElement("span");
        el.textContent = str || "";
        return el.innerHTML;
    },
};
