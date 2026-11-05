import { Gamepad2, Trophy } from "lucide-react";
import type { GameState } from "../types";
import { Artwork } from "./ui/Artwork";

const MEDALS = ["🥇", "🥈", "🥉"];

/** Shown instead of the song while guess the song is running, so the dashboard can't give it away. */
export function GameCard({ game }: { game: GameState }) {
  return (
    <section aria-label="Guess the song" className="mx-auto flex w-full max-w-[560px] flex-col items-center text-center">
      <div className="grid aspect-square w-full max-w-[min(300px,34vh)] place-items-center rounded-[28px] bg-linear-to-br from-accent/40 via-fuchsia-500/20 to-panel ring-1 ring-white/10 short:max-w-[min(200px,22vh)]">
        <Gamepad2 size={88} strokeWidth={1.4} className="text-white/85" />
      </div>
      <p className="mt-6 text-xs font-semibold uppercase tracking-[0.18em] text-accent-3">Guess the song</p>
      <h2 className="mt-2 text-[28px] font-bold tracking-tight">
        Round {game.round || 1} <span className="text-ink-3">of {game.rounds}</span>
      </h2>
      <p className="mt-1.5 text-sm text-ink-2">
        Started by {game.starter}. Type guesses in Discord: title +2, artist +1.
      </p>

      {game.last && (
        <div className="mt-5 flex w-full items-center gap-3 rounded-2xl border border-line bg-panel p-3 text-left">
          <Artwork src={game.last.thumbnail} className="size-12 shrink-0 rounded-xl" iconSize={16} />
          <div className="min-w-0">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">Last answer</div>
            <div className="truncate text-sm font-semibold">{game.last.title}</div>
            {game.last.artist && <div className="truncate text-xs text-ink-2">{game.last.artist}</div>}
          </div>
        </div>
      )}

      <div className="mt-4 w-full rounded-2xl border border-line bg-panel p-4 text-left">
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-ink-3">
          <Trophy size={14} /> Scores
        </div>
        {game.scores.length ? (
          <ol className="space-y-1.5">
            {game.scores.map((s, i) => (
              <li key={s.id} className="flex items-center gap-3 text-sm">
                <span className="w-6 text-center">{MEDALS[i] ?? <span className="text-ink-3 tabular">{i + 1}</span>}</span>
                <span className="min-w-0 flex-1 truncate font-medium">{s.name}</span>
                <span className="font-semibold tabular">{s.points}</span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-ink-3">No points yet. First correct guess takes the lead!</p>
        )}
      </div>
    </section>
  );
}
