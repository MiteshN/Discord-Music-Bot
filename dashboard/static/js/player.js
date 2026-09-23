/**
 * Now-playing card: artwork, track info, progress, transport controls, volume and effects.
 */
const Player = {
    state: null,
    // Position is interpolated locally from the last sync, using the browser's own clock
    pos: { elapsed: 0, rate: 1, paused: true, at: 0 },
    seeking: false,
    lastVolume: 100,
    artUrl: "",

    init() {
        this.el = {
            card: document.getElementById("player"),
            artwork: document.getElementById("artwork"),
            artworkImg: document.getElementById("artwork-img"),
            ambient: document.getElementById("ambient-img"),
            status: document.getElementById("track-status"),
            title: document.getElementById("track-title"),
            meta: document.getElementById("track-meta"),
            badges: document.getElementById("track-badges"),
            seek: document.getElementById("seek"),
            elapsed: document.getElementById("time-elapsed"),
            total: document.getElementById("time-total"),
            play: document.getElementById("btn-play"),
            playIcon: document.getElementById("play-icon"),
            prev: document.getElementById("btn-prev"),
            skip: document.getElementById("btn-skip"),
            stop: document.getElementById("btn-stop"),
            loop: document.getElementById("btn-loop"),
            volume: document.getElementById("volume"),
            volumeValue: document.getElementById("volume-value"),
            volumeIcon: document.getElementById("volume-icon"),
            mute: document.getElementById("btn-mute"),
            tfs: document.getElementById("setting-247"),
            chips: document.querySelectorAll("#effects .chip"),
        };
        const el = this.el;

        this._bind(el.play, () => API.action("player/pause"));
        this._bind(el.skip, () => API.action("player/skip"));
        this._bind(el.prev, () => API.action("player/previous"));
        this._bind(el.stop, () => API.action("player/stop"));
        this._bind(el.loop, () => {
            const next = { off: "track", track: "queue", queue: "off" }[this.state?.loop || "off"];
            return API.action("player/loop", { mode: next });
        });

        // Seek: preview while dragging, send once on release
        el.seek.addEventListener("pointerdown", () => { this.seeking = true; });
        el.seek.addEventListener("input", () => {
            this.seeking = true;
            el.elapsed.textContent = fmt(+el.seek.value);
            setPct(el.seek);
        });
        el.seek.addEventListener("change", async () => {
            const target = +el.seek.value;
            this.pos = { ...this.pos, elapsed: target, at: performance.now() };
            await API.action("player/seek", { position: target });
            this.seeking = false;
        });

        // Volume: preview while dragging, send once on release (each change restarts FFmpeg)
        el.volume.addEventListener("input", () => this._showVolume(+el.volume.value));
        el.volume.addEventListener("change", () => this._sendVolume(+el.volume.value));
        el.mute.addEventListener("click", () => {
            const vol = +el.volume.value > 0 ? 0 : (this.lastVolume || 100);
            this._showVolume(vol);
            this._sendVolume(vol);
        });

        el.tfs.addEventListener("change", () => API.action("settings", { twenty_four_seven: el.tfs.checked }));

        el.chips.forEach(chip => this._bind(chip, () => API.action("player/filter", { filter: chip.dataset.filter })));

        el.artworkImg.addEventListener("load", () => el.artwork.classList.add("has-art"));
        el.artworkImg.addEventListener("error", () => {
            const fallback = ytThumb(this.state?.current?.url, "hqdefault");
            if (fallback && !el.artworkImg.src.endsWith(fallback)) {
                el.artworkImg.src = fallback;
                el.ambient.src = fallback;
            } else {
                el.artwork.classList.remove("has-art");
            }
        });
        el.ambient.addEventListener("load", () => el.ambient.classList.add("visible"));

        setInterval(() => this._tick(), 250);
    },

    /** Run an async action with a busy indicator on the button. */
    _bind(button, action) {
        button.addEventListener("click", async () => {
            if (button.disabled || button.classList.contains("busy")) return;
            button.classList.add("busy");
            try { await action(); } finally { button.classList.remove("busy"); }
        });
    },

    render(s) {
        this.state = s;
        const el = this.el;
        const cur = s.current;
        const active = !!cur && s.in_voice;

        el.card.classList.toggle("is-playing", active && !s.paused);
        el.card.classList.toggle("is-paused", active && s.paused);

        // Artwork + ambient background
        const art = cur?.thumbnail || "";
        if (art !== this.artUrl) {
            this.artUrl = art;
            el.artwork.classList.remove("has-art");
            el.ambient.classList.remove("visible");
            if (art) {
                el.artworkImg.src = art;
                el.ambient.src = art;
            } else {
                el.artworkImg.removeAttribute("src");
                el.ambient.removeAttribute("src");
            }
        }

        // Track text
        if (cur) {
            el.status.textContent = s.paused ? "Paused" : "Now playing";
            el.title.textContent = cur.title;
            if (/^https?:\/\//.test(cur.url)) el.title.href = cur.url; else el.title.removeAttribute("href");
            el.meta.textContent = `Requested by ${cur.requester}`;
        } else {
            el.status.textContent = s.in_voice ? "Ready" : "Not connected";
            el.title.textContent = "Queue something up";
            el.title.removeAttribute("href");
            el.meta.innerHTML = s.in_voice
                ? "Search above, or use <code>/play</code> in Discord."
                : "Join a voice channel in this server, then search above or use <code>/play</code>.";
        }

        el.badges.replaceChildren(...[
            s.filter && badge("graphic_eq", s.filter, true),
            s.loop !== "off" && badge(s.loop === "track" ? "repeat_one" : "repeat", s.loop === "track" ? "Looping track" : "Looping queue"),
            s.twenty_four_seven && badge("schedule", "24/7"),
            cur && cur.duration === 0 && badge("sensors", "Live"),
        ].filter(Boolean));

        // Progress
        const duration = cur?.duration || 0;
        el.seek.max = duration || 100;
        el.seek.disabled = !active || !duration;
        el.total.textContent = duration ? fmt(duration) : (cur ? "Live" : "0:00");
        this.syncPosition(s);

        // Controls
        el.playIcon.textContent = active && !s.paused ? "pause" : "play_arrow";
        el.play.disabled = !active;
        el.skip.disabled = !active;
        el.stop.disabled = !s.in_voice;
        el.prev.disabled = !s.in_voice || !s.has_previous;
        el.loop.classList.toggle("on", s.loop !== "off");
        el.loop.querySelector(".icon").textContent = s.loop === "track" ? "repeat_one" : "repeat";
        el.loop.title = `Loop (${s.loop})`;

        if (!el.volume.matches(":active")) this._showVolume(s.volume);
        el.tfs.checked = !!s.twenty_four_seven;

        el.chips.forEach(chip => {
            chip.classList.toggle("active", chip.dataset.filter === (s.filter_key || ""));
            chip.disabled = !active;
        });
    },

    syncPosition(p) {
        this.pos = { elapsed: p.elapsed || 0, rate: p.rate || 1, paused: !!p.paused, at: performance.now() };
        this._tick();
    },

    _tick() {
        const cur = this.state?.current;
        if (this.seeking) return;
        if (!cur) {
            this.el.seek.value = 0;
            this.el.elapsed.textContent = "0:00";
            setPct(this.el.seek);
            return;
        }
        let t = this.pos.elapsed;
        if (!this.pos.paused && this.state.in_voice) t += (performance.now() - this.pos.at) / 1000 * this.pos.rate;
        if (cur.duration) t = Math.min(t, cur.duration);
        this.el.seek.value = Math.floor(t);
        this.el.elapsed.textContent = fmt(t);
        setPct(this.el.seek);
    },

    _showVolume(vol) {
        const el = this.el;
        el.volume.value = vol;
        el.volumeValue.textContent = `${vol}%`;
        el.volumeIcon.textContent = vol === 0 ? "volume_off" : vol < 50 ? "volume_down" : "volume_up";
        if (vol > 0) this.lastVolume = vol;
        setPct(el.volume);
    },

    _sendVolume(vol) {
        API.action("player/volume", { volume: vol });
    },

    /** Clear everything from the previous server straight away, before the new server's state arrives. */
    reset() {
        const el = this.el;
        this.state = null;
        this.artUrl = "";
        el.artwork.classList.remove("has-art");
        el.artworkImg.removeAttribute("src");
        el.ambient.classList.remove("visible");
        el.ambient.removeAttribute("src");
        el.seek.max = 100;
        this._tick();
    },
};

function fmt(seconds) {
    seconds = Math.max(0, Math.floor(seconds || 0));
    const h = Math.floor(seconds / 3600);
    const m = Math.floor(seconds / 60) % 60;
    const s = String(seconds % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

function setPct(input) {
    const max = +input.max || 100;
    input.style.setProperty("--pct", `${Math.min(100, (+input.value / max) * 100)}%`);
}

function badge(icon, text, accent = false) {
    const el = document.createElement("span");
    el.className = accent ? "badge accent" : "badge";
    const i = document.createElement("span");
    i.className = "icon";
    i.textContent = icon;
    el.append(i, text);
    return el;
}
