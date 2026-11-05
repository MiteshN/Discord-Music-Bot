from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from mugetsu.player.manager import Requester
from mugetsu.player.models import PlayerError, Song
from mugetsu.ui import embeds
from mugetsu.util import format_duration

if TYPE_CHECKING:
    from mugetsu.bot import MugetsuBot

NUMBERS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣"]


class NowPlayingView(discord.ui.View):
    """Playback buttons under the now-playing message."""

    def __init__(self, bot: MugetsuBot, guild_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        self.message: discord.PartialMessage | None = None
        if bot.config.public_dashboard_url:
            self.add_item(discord.ui.Button(label="Dashboard", emoji="🎛️", url=bot.config.public_dashboard_url, row=1))

    @property
    def player(self):
        return self.bot.players.get(self.guild_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        vc = interaction.guild.voice_client
        voice = interaction.user.voice
        if vc and voice and voice.channel == vc.channel:
            return True
        await interaction.response.send_message("Join my voice channel to use these controls.", ephemeral=True)
        return False

    async def _run(self, interaction: discord.Interaction, action):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            message = await action
        except PlayerError as e:
            message = str(e)
        await interaction.followup.send(message, ephemeral=True)

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary, row=0)
    async def previous_button(self, interaction: discord.Interaction, _):
        await self._run(interaction, self.player.previous(interaction.user))

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, row=0)
    async def pause_button(self, interaction: discord.Interaction, _):
        await self._run(interaction, self.player.toggle_pause(interaction.user))

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def skip_button(self, interaction: discord.Interaction, _):
        await self._run(interaction, self.player.skip(interaction.user))

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=0)
    async def stop_button(self, interaction: discord.Interaction, _):
        await self._run(interaction, self.player.stop(interaction.user))

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, row=1)
    async def loop_button(self, interaction: discord.Interaction, _):
        await self._run(interaction, self.player.set_loop(None, interaction.user))

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, row=1)
    async def shuffle_button(self, interaction: discord.Interaction, _):
        await self._run(interaction, self.player.shuffle(interaction.user))

    @discord.ui.button(emoji="📜", label="Queue", style=discord.ButtonStyle.secondary, row=1)
    async def queue_button(self, interaction: discord.Interaction, _):
        await interaction.response.send_message(embed=embeds.queue_page(self.player), ephemeral=True)


class SearchSelectView(discord.ui.View):
    def __init__(self, bot: MugetsuBot, author: discord.Member, results: list[dict]):
        super().__init__(timeout=60)
        self.bot = bot
        self.author = author
        self.results = results
        self.message: discord.Message | None = None
        self.select = discord.ui.Select(
            placeholder="Pick a track…",
            options=[
                discord.SelectOption(
                    label=r["title"][:100],
                    description=format_duration(r["duration"]),
                    value=str(i),
                    emoji=NUMBERS[i] if i < len(NUMBERS) else None,
                )
                for i, r in enumerate(results)
            ],
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("This isn't your search.", ephemeral=True)
            return
        await interaction.response.defer()
        self.stop()
        chosen = self.results[int(self.select.values[0])]
        song = Song(
            title=chosen["title"], query=chosen["url"], url=chosen["url"],
            duration=chosen["duration"], thumbnail=chosen["thumbnail"],
            **Requester.of(interaction.user).fields(),
        )
        try:
            await self.bot.players.join(interaction.user)
            await self.bot.announcer.enqueue_and_reply(
                self.bot.players.get(interaction.guild_id), [song], "", channel_id=interaction.channel_id,
                send=lambda **kw: interaction.followup.send(wait=True, **kw), actor=interaction.user,
            )
        except PlayerError as e:
            await interaction.followup.send(str(e), ephemeral=True)
        await interaction.edit_original_response(view=None)

    async def on_timeout(self):
        if self.message:
            self.select.disabled = True
            self.select.placeholder = "Search timed out"
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
