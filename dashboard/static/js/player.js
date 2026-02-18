/**
 * Player UI: bottom controller bar, seek bar interpolation, state display.
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
            const val = parseInt(volSlider.value);
            document.getElementById("volume-label").textContent = val + "%";
            this._updateVolumeIcon(val);
            this._updateRangeFill(volSlider);
            clearTimeout(volTimeout);
            volTimeout = setTimeout(() => {
                if (App.guildId) API.setVolume(App.guildId, val);
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
            this._updateRangeFill(seekBar);
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

        // Hero area: title / artwork
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

        // Filter badge in hero
        const filterBadge = document.getElementById("player-filter");
        if (data.filter) {
            filterBadge.textContent = data.filter;
            filterBadge.style.display = "inline-block";
        } else {
            filterBadge.style.display = "none";
        }

        // Bottom controller: track info
        const ctrlArtwork = document.getElementById("ctrl-artwork");
        if (data.current.thumbnail) {
            ctrlArtwork.src = data.current.thumbnail;
            ctrlArtwork.style.display = "block";
        } else {
            ctrlArtwork.style.display = "none";
        }
        document.getElementById("ctrl-title").textContent = data.current.title;
        document.getElementById("ctrl-requester").textContent = data.current.requester;

        // Seek bar
        const seekBar = document.getElementById("seek-bar");
        const duration = data.current.duration || 0;
        seekBar.max = duration;
        if (!this.isSeeking) {
            seekBar.value = Math.floor(data.elapsed || 0);
            document.getElementById("elapsed-time").textContent =
                this._formatTime(Math.floor(data.elapsed || 0));
            this._updateRangeFill(seekBar);
        }
        document.getElementById("total-time").textContent = this._formatTime(duration);

        // Play/pause icon
        document.getElementById("play-pause-icon").textContent =
            data.paused ? "play_arrow" : "pause";

        // Volume
        const volSlider = document.getElementById("volume-slider");
        if (!volSlider.matches(":active")) {
            volSlider.value = data.volume;
            document.getElementById("volume-label").textContent = data.volume + "%";
            this._updateVolumeIcon(data.volume);
            this._updateRangeFill(volSlider);
        }

        // Loop
        document.getElementById("loop-select").value = data.loop || "off";

        // Filter select
        const filterMap = {
            "": "clear", "Nightcore": "nightcore", "Vaporwave": "vaporwave",
            "Bass Boost": "bassboost", "Tremolo": "tremolo", "Vibrato": "vibrato", "8D": "8d",
        };
        document.getElementById("filter-select").value = filterMap[data.filter] || "clear";

        // Update queue now playing
        Queue.updateNowPlaying(data.current);
    },

    updatePosition(data) {
        this.state.elapsed = data.elapsed;
        this.state.paused = data.paused;
        this.state.playing = data.playing;
        this.state.timestamp = data.timestamp;

        // Update play/pause icon
        document.getElementById("play-pause-icon").textContent =
            data.paused ? "play_arrow" : "pause";
    },

    updateVolume(vol) {
        this.state.volume = vol;
        const volSlider = document.getElementById("volume-slider");
        if (!volSlider.matches(":active")) {
            volSlider.value = vol;
            document.getElementById("volume-label").textContent = vol + "%";
            this._updateVolumeIcon(vol);
            this._updateRangeFill(volSlider);
        }
    },

    updateLoop(mode) {
        this.state.loop = mode;
        document.getElementById("loop-select").value = mode;
    },

    showIdle() {
        document.getElementById("player-idle").style.display = "flex";
        document.getElementById("player-active").style.display = "none";

        // Clear controller
        document.getElementById("ctrl-artwork").style.display = "none";
        document.getElementById("ctrl-title").textContent = "";
        document.getElementById("ctrl-requester").textContent = "";
        document.getElementById("play-pause-icon").textContent = "play_arrow";

        const seekBar = document.getElementById("seek-bar");
        seekBar.value = 0;
        seekBar.max = 100;
        this._updateRangeFill(seekBar);
        document.getElementById("elapsed-time").textContent = "0:00";
        document.getElementById("total-time").textContent = "0:00";

        // Clear queue now playing
        Queue.updateNowPlaying(null);
    },

    showActive() {
        document.getElementById("player-idle").style.display = "none";
        document.getElementById("player-active").style.display = "flex";
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
        this._updateRangeFill(seekBar);
    },

    _formatTime(seconds) {
        if (seconds <= 0) return "0:00";
        const s = seconds % 60;
        const m = Math.floor(seconds / 60) % 60;
        const h = Math.floor(seconds / 3600);
        if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
        return `${m}:${String(s).padStart(2, "0")}`;
    },

    _updateRangeFill(input) {
        const min = parseFloat(input.min) || 0;
        const max = parseFloat(input.max) || 100;
        const val = parseFloat(input.value) || 0;
        const pct = max > min ? ((val - min) / (max - min)) * 100 : 0;
        input.style.background = `linear-gradient(to right, var(--text-primary) 0%, var(--text-primary) ${pct}%, var(--bg-lighter) ${pct}%, var(--bg-lighter) 100%)`;
    },

    _updateVolumeIcon(vol) {
        const icon = document.getElementById("volume-icon");
        if (vol === 0) icon.textContent = "volume_off";
        else if (vol < 40) icon.textContent = "volume_down";
        else icon.textContent = "volume_up";
    },
};
