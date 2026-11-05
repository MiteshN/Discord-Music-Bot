import type { BotInfo, Guild, LyricsData, PlayerState, SearchResults, User } from "../types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const headers: Record<string, string> = {};
  if (method !== "GET") headers["X-Requested-With"] = "mugetsu";
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError("Can't reach Mugetsu. Is the bot running?", 0);
  }

  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    /* empty body */
  }
  if (!res.ok) {
    const message = (data as { error?: string } | null)?.error ?? `Request failed (${res.status})`;
    throw new ApiError(message, res.status);
  }
  return data as T;
}

export const api = {
  me: () => request<{ user: User; bot: BotInfo }>("GET", "/api/me"),
  logout: () => request<{ ok: boolean }>("POST", "/api/logout"),
  guilds: () => request<Guild[]>("GET", "/api/guilds"),
  state: (guildId: string) => request<PlayerState>("GET", `/api/guilds/${guildId}/state`),
  act: (guildId: string, action: string, args: Record<string, unknown> = {}) =>
    request<{ message: string }>("POST", `/api/guilds/${guildId}/actions/${action}`, args),
  search: (guildId: string, query: string, signal?: AbortSignal) =>
    request<SearchResults>("GET", `/api/guilds/${guildId}/search?q=${encodeURIComponent(query)}`, undefined, signal),
  lyrics: (guildId: string, signal?: AbortSignal) =>
    request<LyricsData>("GET", `/api/guilds/${guildId}/lyrics`, undefined, signal),
};
