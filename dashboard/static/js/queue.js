/**
 * Queue list UI with remove and drag-and-drop reorder.
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

    _render() {
        const list = document.getElementById("queue-list");
        const empty = document.getElementById("queue-empty");
        const countEl = document.getElementById("queue-count");

        if (!this.items.length) {
            list.innerHTML = '<li class="queue-empty">Queue is empty</li>';
            countEl.textContent = "";
            return;
        }

        countEl.textContent = `(${this.items.length})`;

        list.innerHTML = this.items.map((song, i) => `
            <li class="queue-item" draggable="true" data-index="${i}">
                <span class="queue-item-index">${i + 1}</span>
                ${song.thumbnail
                    ? `<img class="queue-item-thumb" src="${this._esc(song.thumbnail)}" alt="">`
                    : '<div class="queue-item-thumb"></div>'}
                <div class="queue-item-info">
                    <div class="queue-item-title">${this._esc(song.title)}</div>
                    <div class="queue-item-meta">
                        ${song.duration ? Player._formatTime(song.duration) : "Unknown"} &middot; ${this._esc(song.requester)}
                    </div>
                </div>
                <div class="queue-item-actions">
                    <button class="queue-item-btn" data-remove="${i}" title="Remove">&#x2715;</button>
                </div>
            </li>
        `).join("");

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

    _esc(str) {
        const el = document.createElement("span");
        el.textContent = str || "";
        return el.innerHTML;
    },
};
