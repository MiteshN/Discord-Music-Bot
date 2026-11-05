import { useEffect } from "react";
import { useStore } from "../store";
import type { SocketMessage } from "../types";

/** Live player state for the selected server, reconnecting with backoff when the connection drops. */
export function useGuildSocket(guildId: string | null) {
  useEffect(() => {
    if (!guildId) return;
    const store = useStore.getState;
    let socket: WebSocket | null = null;
    let retryDelay = 1000;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;

    const connect = () => {
      clearTimeout(timer);
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/ws/guilds/${guildId}`);
      socket = ws;

      ws.onopen = () => {
        retryDelay = 1000;
        store().setConnection("live");
      };
      ws.onmessage = (event) => {
        let msg: SocketMessage;
        try {
          msg = JSON.parse(event.data);
        } catch {
          return;
        }
        if (msg.type === "state") store().setPlayer(msg.data);
        else if (msg.type === "position") store().syncPosition(msg.data);
        else if (msg.type === "activity") store().onActivity(msg.data);
      };
      ws.onclose = (event) => {
        if (disposed || socket !== ws) return;
        if (event.code === 4001) {
          store().signedOut();
          return;
        }
        if (event.code === 4003) {
          store().setConnection("idle");
          store().toast("You don't have access to that server.", "error");
          return;
        }
        store().setConnection("reconnecting");
        timer = setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 15000);
      };
    };

    // Phones suspend background tabs: reconnect the moment we're visible again
    const onVisible = () => {
      if (document.visibilityState === "visible" && socket && socket.readyState > WebSocket.OPEN) {
        retryDelay = 1000;
        connect();
      }
    };

    connect();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      disposed = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
      if (socket) {
        socket.onmessage = null;
        socket.onclose = null;
        socket.close();
      }
    };
  }, [guildId]);
}
