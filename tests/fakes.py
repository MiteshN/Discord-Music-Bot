"""Just enough of discord.py's voice objects to drive the playback engine in tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace


class FakeAvatar:
    def __init__(self, url="https://cdn.example/avatar.png"):
        self.url = url

    def with_size(self, _size):
        return self


@dataclass(eq=False)
class FakeRole:
    name: str


@dataclass
class FakePerms:
    administrator: bool = False
    connect: bool = True
    speak: bool = True


@dataclass(eq=False)
class FakeMember:
    id: int
    display_name: str
    guild: FakeGuild | None = None
    roles: list = field(default_factory=list)
    admin: bool = False
    bot: bool = False
    voice: SimpleNamespace | None = None
    display_avatar: FakeAvatar = field(default_factory=FakeAvatar)

    @property
    def guild_permissions(self):
        return FakePerms(administrator=self.admin)

    @property
    def mention(self):
        return f"<@{self.id}>"


@dataclass(eq=False)
class FakeVoiceChannel:
    id: int
    name: str
    guild: FakeGuild
    members: list = field(default_factory=list)
    bitrate: int = 96000
    statuses: list = field(default_factory=list)

    @property
    def mention(self):
        return f"<#{self.id}>"

    async def edit(self, *, status=None):
        self.statuses.append(status)

    def permissions_for(self, _member):
        return FakePerms()

    async def connect(self, *, self_deaf=True, timeout=20):
        vc = FakeVoiceClient(self)
        self.guild.voice_client = vc
        return vc

    async def send(self, *args, **kwargs):
        self.guild.sent.append((args, kwargs))


class FakeVoiceClient:
    def __init__(self, channel: FakeVoiceChannel):
        self.channel = channel
        self.guild = channel.guild
        self.connected = True
        self.source = None
        self.paused = False
        self._after = None
        self.played = []

    def is_connected(self):
        return self.connected

    def is_playing(self):
        return self.source is not None and not self.paused

    def is_paused(self):
        return self.source is not None and self.paused

    def play(self, source, *, after=None):
        assert self.source is None, "play() while already playing"
        self.source = source
        self.paused = False
        self._after = after
        self.played.append(source)

    def _end(self, error=None):
        after, self._after = self._after, None
        self.source = None
        self.paused = False
        if after:
            after(error)

    def stop(self):
        if self.source is not None:
            self._end()

    def finish(self, error: Exception | None = None):
        """The track played to the end, or (with an error) the audio thread died, as discord.py reports it."""
        self._end(error)

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    async def disconnect(self, *, force=False):
        self.stop()
        self.connected = False
        self.guild.voice_client = None

    async def move_to(self, channel):
        self.channel = channel


class FakeGuild:
    def __init__(self, guild_id=1, *, dj_role=False):
        self.id = guild_id
        self.name = f"Guild {guild_id}"
        self.roles = [FakeRole("DJ")] if dj_role else []
        self.voice_client: FakeVoiceClient | None = None
        self.me = FakeMember(999, "Mugetsu", self, bot=True)
        self.channel = FakeVoiceChannel(10, "Lounge", self)
        self.members: dict[int, FakeMember] = {}
        self.fetchable: dict[int, FakeMember] = {}
        self.sent = []
        self.icon = None

    def member(self, member_id, name, *, dj=False, admin=False, in_voice=True) -> FakeMember:
        m = FakeMember(member_id, name, self, admin=admin)
        if dj:
            m.roles.append(self.roles[0])
        if in_voice:
            m.voice = SimpleNamespace(channel=self.channel)
            self.channel.members.append(m)
            self.members[member_id] = m
        else:
            self.fetchable[member_id] = m
        return m

    def get_member(self, member_id):
        return self.members.get(member_id)

    async def fetch_member(self, member_id):
        if member_id in self.fetchable:
            return self.fetchable[member_id]
        import discord

        raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Member")

    def get_channel(self, channel_id):
        return self.channel if channel_id == self.channel.id else None

    get_channel_or_thread = get_channel


class FakeBot:
    def __init__(self, *guilds: FakeGuild):
        self._guilds = {g.id: g for g in guilds}
        self.user = FakeMember(999, "Mugetsu", bot=True)

    @property
    def guilds(self):
        return list(self._guilds.values())

    def get_guild(self, guild_id):
        return self._guilds.get(guild_id)

    @property
    def voice_clients(self):
        return [g.voice_client for g in self._guilds.values() if g.voice_client]

    def is_ready(self):
        return True

    async def wait_until_ready(self):
        return None
