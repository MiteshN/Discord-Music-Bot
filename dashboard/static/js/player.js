/**
 * Player UI: controls, seek bar interpolation, state display.
 */
const Player = {
    state: {
        current: null,
        elapsed: 0,
        paused: false,
        playing: false,
        volume: 50,
        loop: "off",
        filter: "",
        timestamp: 0,
        in_voice: false,
    },
    seekInterval: null,
    isSeeking: false,

    init() {
        // Play/Pause
        document.getElementById("btn-play-pause").addEventListener("click", () => {
            if (App.guildId) API.pauseResume(App.guildId);
        });

        // Skip
        document.getElementById("btn-skip").addEventListener("click", () => {
            if (App.guildId) API.skip(App.guildId);
        });

        // Stop
        document.getElementById("btn-stop").addEventListener("click", () => {
            if (App.guildId) API.stop(App.guildId);
        });

        // Shuffle (control row)
        document.getElementById("btn-shuffle").addEventListener("click", () => {
            if (App.guildId) API.shuffleQueue(App.guildId);
        });

        // Volume
        const volSlider = document.getElementById("volume-slider");
        let volTimeout = null;
        volSlider.addEventListener("input", () => {
            document.getElementById("volume-label").textContent = volSlider.value + "%";
            clearTimeout(volTimeout);
            volTimeout = setTimeout(() => {
                if (App.guildId) API.setVolume(App.guildId, parseInt(volSlider.value));
            }, 300);
        });

        // Loop
        document.getElementById("loop-select").addEventListener("change", (e) => {
            if (App.guildId) API.setLoop(App.guildId, e.target.value);
        });

        // Filter
        document.getElementById("filter-select").addEventListener("change", (e) => {
            if (App.guildId) API.setFilter(App.guildId, e.target.value);
        });

        // Seek bar
        const seekBar = document.getElementById("seek-bar");
        seekBar.addEventListener("mousedown", () => { this.isSeeking = true; });
        seekBar.addEventListener("touchstart", () => { this.isSeeking = true; });
        seekBar.addEventListener("change", () => {
            this.isSeeking = false;
            if (App.guildId && this.state.current) {
                API.seek(App.guildId, parseInt(seekBar.value));
            }
        });
        seekBar.addEventListener("input", () => {
            document.getElementById("elapsed-time").textContent =
                this._formatTime(parseInt(seekBar.value));
        });

        // Start interpolation
        this.seekInterval = setInterval(() => this._interpolate(), 500);
    },

    updateFull(data) {
        this.state = { ...this.state, ...data };

        if (!data.current) {
            this.showIdle();
            return;
        }

        this.showActive();

        // Title / artwork
        const titleLink = document.getElementById("player-title-link");
        titleLink.textContent = data.current.title;
        titleLink.href = data.current.url || "#";

        document.getElementById("player-requester").textContent =
            `Requested by ${data.current.requester}`;

        const artwork = document.getElementById("player-artwork");
        if (data.current.thumbnail) {
            artwork.src = data.current.thumbnail;
            artwork.style.display = "block";
        } else {
            artwork.style.display = "none";
        }

        // Filter badge
        const filterBadge = document.getElementById("player-filter");
        if (data.filter) {
            filterBadge.textContent = data.filter;
            filterBadge.style.display = "inline-block";
        } else {
            filterBadge.style.display = "none";
        }

        // Seek bar
        const seekBar = document.getElementById("seek-bar");
        const duration = data.current.duration || 0;
        seekBar.max = duration;
        if (!this.isSeeking) {
            seekBar.value = Math.floor(data.elapsed || 0);
            document.getElementById("elapsed-time").textContent =
                this._formatTime(Math.floor(data.elapsed || 0));
        }
        document.getElementById("total-time").textContent = this._formatTime(duration);

        // Play/pause button
        const btn = document.getElementById("btn-play-pause");
        btn.innerHTML = data.paused ? "&#x25B6;" : "&#x23F8;";

        // Volume
        if (!document.getElementById("volume-slider").matches(":active")) {
            document.getElementById("volume-slider").value = data.volume;
            document.getElementById("volume-label").textContent = data.volume + "%";
        }

        // Loop
        document.getElementById("loop-select").value = data.loop || "off";

        // Filter select
        const filterMap = {
            "": "clear", "Nightcore": "nightcore", "Vaporwave": "vaporwave",
            "Bass Boost": "bassboost", "Tremolo": "tremolo", "Vibrato": "vibrato", "8D": "8d",
        };
        document.getElementById("filter-select").value = filterMap[data.filter] || "clear";
    },

    updatePosition(data) {
        this.state.elapsed = data.elapsed;
        this.state.paused = data.paused;
        this.state.playing = data.playing;
        this.state.timestamp = data.timestamp;

        // Update play/pause icon
        const btn = document.getElementById("btn-play-pause");
        btn.innerHTML = data.paused ? "&#x25B6;" : "&#x23F8;";
    },

    updateVolume(vol) {
        this.state.volume = vol;
        if (!document.getElementById("volume-slider").matches(":active")) {
            document.getElementById("volume-slider").value = vol;
            document.getElementById("volume-label").textContent = vol + "%";
        }
    },

    updateLoop(mode) {
        this.state.loop = mode;
        document.getElementById("loop-select").value = mode;
    },

    showIdle() {
        document.getElementById("player-idle").style.display = "block";
        document.getElementById("player-active").style.display = "none";
    },

    showActive() {
        document.getElementById("player-idle").style.display = "none";
        document.getElementById("player-active").style.display = "block";
    },

    _interpolate() {
        if (!this.state.current || this.state.paused || this.isSeeking) return;
        const now = Date.now() / 1000;
        const elapsed = this.state.elapsed + (now - this.state.timestamp);
        const duration = this.state.current.duration || 0;
        const clamped = duration > 0 ? Math.min(elapsed, duration) : elapsed;

        const seekBar = document.getElementById("seek-bar");
        seekBar.value = Math.floor(clamped);
        document.getElementById("elapsed-time").textContent =
            this._formatTime(Math.floor(clamped));
    },

    _formatTime(seconds) {
        if (seconds <= 0) return "0:00";
        const s = seconds % 60;
        const m = Math.floor(seconds / 60) % 60;
        const h = Math.floor(seconds / 3600);
        if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
        return `${m}:${String(s).padStart(2, "0")}`;
    },
};
