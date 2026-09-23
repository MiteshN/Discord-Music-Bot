/**
 * Queue panel: list with drag-and-drop reordering, move-to-top and remove.
 */
const Queue = {
    signature: "",
    dragFrom: null,

    init() {
        this.list = document.getElementById("queue-list");
        this.empty = document.getElementById("queue-empty");
        this.summary = document.getElementById("queue-summary");

        document.getElementById("btn-shuffle").addEventListener("click", () => API.action("queue/shuffle"));
        document.getElementById("btn-clear").addEventListener("click", () => {
            if (confirm("Clear the whole queue?")) API.action("queue/clear");
        });

        // Event delegation: one set of listeners for the whole list
        this.list.addEventListener("click", (e) => {
            const btn = e.target.closest("[data-action]");
            if (!btn) return;
            const index = +btn.closest(".q-item").dataset.index;
            if (btn.dataset.action === "remove") API.removeFromQueue(index);
            if (btn.dataset.action === "top") API.action("queue/move", { from: index, to: 0 });
        });
        this.list.addEventListener("dragstart", (e) => {
            const item = e.target.closest(".q-item");
            if (!item) return;
            this.dragFrom = +item.dataset.index;
            item.classList.add("dragging");
            e.dataTransfer.effectAllowed = "move";
        });
        this.list.addEventListener("dragend", () => {
            this.dragFrom = null;
            this.list.querySelectorAll(".dragging, .drop-before, .drop-after")
                .forEach(el => el.classList.remove("dragging", "drop-before", "drop-after"));
        });
        this.list.addEventListener("dragover", (e) => {
            const item = e.target.closest(".q-item");
            if (!item || this.dragFrom === null) return;
            e.preventDefault();
            const after = +item.dataset.index > this.dragFrom;
            this.list.querySelectorAll(".drop-before, .drop-after").forEach(el => el.classList.remove("drop-before", "drop-after"));
            item.classList.add(after ? "drop-after" : "drop-before");
        });
        this.list.addEventListener("drop", (e) => {
            const item = e.target.closest(".q-item");
            if (!item || this.dragFrom === null) return;
            e.preventDefault();
            const to = +item.dataset.index;
            if (to !== this.dragFrom) API.action("queue/move", { from: this.dragFrom, to });
        });
    },

    render(s) {
        const total = s.queue_length || 0;
        this.summary.textContent = total
            ? `${total} track${total === 1 ? "" : "s"}${s.queue_duration ? ` · ${fmtLong(s.queue_duration)}` : ""}`
            : "Empty";
        document.getElementById("tab-count").textContent = total || "";
        document.getElementById("btn-shuffle").disabled = total < 2;
        document.getElementById("btn-clear").disabled = total === 0;

        // Skip the DOM rebuild if nothing visible changed
        const signature = JSON.stringify([s.queue, total]);
        if (signature === this.signature) return;
        this.signature = signature;

        this.empty.hidden = total > 0;
        this.list.hidden = total === 0;
        this.list.replaceChildren(...s.queue.map((song, i) => this._item(song, i)));
        if (total > s.queue.length) {
            const more = document.createElement("li");
            more.className = "queue-more";
            more.textContent = `+ ${total - s.queue.length} more`;
            this.list.append(more);
        }
    },

    _item(song, i) {
        const li = document.createElement("li");
        li.className = "q-item";
        li.draggable = true;
        li.dataset.index = i;
        li.innerHTML = `
            <span class="q-index">${i + 1}</span>
            <span class="icon q-handle">drag_indicator</span>
            <img class="q-thumb" alt="" loading="lazy">
            <div class="q-info">
                <div class="q-title"></div>
                <div class="q-meta"></div>
            </div>
            <div class="q-actions">
                ${i > 0 ? '<button class="q-btn" data-action="top" title="Play next"><span class="icon">vertical_align_top</span></button>' : ""}
                <button class="q-btn danger" data-action="remove" title="Remove"><span class="icon">close</span></button>
            </div>`;
        // Small YouTube thumbnails always exist (maxres ones don't); keep other art such as Spotify covers
        const thumb = song.thumbnail && !song.thumbnail.includes("i.ytimg.com")
            ? song.thumbnail : (ytThumb(song.url) || song.thumbnail);
        if (thumb) li.querySelector(".q-thumb").src = thumb;
        li.querySelector(".q-title").textContent = song.title;
        li.querySelector(".q-meta").textContent = `${song.duration ? fmt(song.duration) : "—"} · ${song.requester}`;
        return li;
    },
};

function ytThumb(url, size = "mqdefault") {
    const m = (url || "").match(/(?:v=|youtu\.be\/)([A-Za-z0-9_-]{11})/);
    return m ? `https://i.ytimg.com/vi/${m[1]}/${size}.jpg` : "";
}

function fmtLong(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.round((seconds % 3600) / 60);
    return h ? `${h} hr ${m} min` : `${m} min`;
}
