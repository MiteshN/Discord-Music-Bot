import { AudioLines, ListMusic, MicVocal, RefreshCw, Zap } from "lucide-react";
import { Logo } from "./Logo";

const FEATURES = [
  { icon: Zap, text: "Live sync" },
  { icon: ListMusic, text: "Queue control" },
  { icon: MicVocal, text: "Synced lyrics" },
  { icon: AudioLines, text: "Effects" },
];

const LOGIN_ERRORS: Record<string, string> = {
  failed: "Discord sign-in didn't work. Please try again.",
  expired: "That sign-in link expired. Please try again.",
  cancelled: "Sign-in was cancelled.",
};

function DiscordMark() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M20.32 4.37a19.8 19.8 0 0 0-4.89-1.52.07.07 0 0 0-.08.04c-.21.38-.44.86-.6 1.25a18.27 18.27 0 0 0-5.49 0 12.6 12.6 0 0 0-.62-1.25.08.08 0 0 0-.08-.04 19.74 19.74 0 0 0-4.88 1.52.07.07 0 0 0-.04.03C.53 9.05-.32 13.58.1 18.06a.08.08 0 0 0 .03.05 19.9 19.9 0 0 0 6 3.03.08.08 0 0 0 .08-.03c.46-.63.87-1.3 1.23-1.99a.08.08 0 0 0-.04-.1 13.1 13.1 0 0 1-1.87-.9.08.08 0 0 1-.01-.12l.37-.3a.07.07 0 0 1 .08-.01c3.93 1.8 8.18 1.8 12.06 0a.07.07 0 0 1 .08 0l.37.3a.08.08 0 0 1 0 .13 12.3 12.3 0 0 1-1.88.9.08.08 0 0 0-.04.1c.36.7.78 1.36 1.23 2a.08.08 0 0 0 .08.02 19.84 19.84 0 0 0 6-3.03.08.08 0 0 0 .04-.05c.5-5.18-.84-9.68-3.55-13.66a.06.06 0 0 0-.03-.03zM8.02 15.33c-1.18 0-2.16-1.08-2.16-2.42 0-1.33.96-2.42 2.16-2.42 1.21 0 2.18 1.1 2.16 2.42 0 1.34-.96 2.42-2.16 2.42zm7.97 0c-1.18 0-2.15-1.08-2.15-2.42 0-1.33.95-2.42 2.15-2.42 1.21 0 2.18 1.1 2.16 2.42 0 1.34-.95 2.42-2.16 2.42z" />
    </svg>
  );
}

export function Login({ offline = false }: { offline?: boolean }) {
  const reason = new URLSearchParams(location.search).get("login");
  const message = offline ? "Can't reach Mugetsu right now. Is the bot running?" : reason ? LOGIN_ERRORS[reason] : null;

  return (
    <main className="relative grid min-h-full place-items-center overflow-y-auto px-4 py-12">
      <div aria-hidden className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute -left-40 -top-40 size-[36rem] rounded-full bg-accent/25 blur-[120px]" />
        <div className="absolute -bottom-48 -right-24 size-[32rem] rounded-full bg-sky-500/10 blur-[120px]" />
        <div className="absolute left-1/2 top-1/3 size-[22rem] -translate-x-1/2 rounded-full bg-fuchsia-500/10 blur-[100px]" />
      </div>

      <div className="relative w-full max-w-md animate-rise rounded-[28px] border border-line bg-white/[0.04] p-8 text-center shadow-[0_40px_120px_-30px_rgb(0_0_0/0.8)] backdrop-blur-2xl sm:p-10">
        <Logo className="mx-auto size-16 shadow-[0_18px_50px_-10px_rgb(139_92_246/0.7)]" />
        <h1 className="mt-6 text-3xl font-bold tracking-tight">Mugetsu</h1>
        <p className="mx-auto mt-3 max-w-xs text-[15px] leading-relaxed text-ink-2">
          Your server's music, from any browser. Search, queue and control playback in real time.
        </p>

        {message && (
          <p role="alert" className="mt-6 rounded-xl border border-danger/25 bg-danger/10 px-4 py-2.5 text-sm text-danger">
            {message}
          </p>
        )}

        {offline ? (
          <button
            type="button"
            onClick={() => location.reload()}
            className="mt-8 inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-panel-3 px-5 py-3.5 font-semibold transition hover:bg-white/15"
          >
            <RefreshCw size={18} /> Try again
          </button>
        ) : (
          <a
            href="/login"
            className="mt-8 inline-flex w-full items-center justify-center gap-3 rounded-2xl bg-[#5865f2] px-5 py-3.5 font-semibold text-white shadow-[0_12px_32px_-10px_rgb(88_101_242/0.8)] transition hover:-translate-y-px hover:bg-[#6773f4] active:translate-y-0"
          >
            <DiscordMark /> Continue with Discord
          </a>
        )}

        <ul className="mt-8 grid grid-cols-2 gap-2 text-left text-[13px] text-ink-2 sm:grid-cols-4 sm:text-center">
          {FEATURES.map(({ icon: Icon, text }) => (
            <li key={text} className="flex items-center gap-2 rounded-xl bg-panel px-3 py-2 sm:flex-col sm:gap-1.5 sm:py-3">
              <Icon size={16} className="shrink-0 text-accent-3" />
              {text}
            </li>
          ))}
        </ul>
        <p className="mt-6 text-xs text-ink-3">We only ask Discord for your name and which servers you're in.</p>
      </div>
    </main>
  );
}
