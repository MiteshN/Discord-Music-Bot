import { useEffect } from "react";
import { Dashboard } from "./components/Dashboard";
import { Login } from "./components/Login";
import { Logo } from "./components/Logo";
import { useStore } from "./store";

export function App() {
  const auth = useStore((s) => s.auth);
  const boot = useStore((s) => s.boot);

  useEffect(() => {
    boot();
  }, [boot]);

  // Drop ?login=… from the address bar once we've read it
  useEffect(() => {
    if (auth === "signed-in" && location.search) history.replaceState(null, "", location.pathname);
  }, [auth]);

  if (auth === "loading") {
    return (
      <div className="grid h-full place-items-center">
        <Logo className="size-14 animate-pulse" />
      </div>
    );
  }
  if (auth === "signed-out" || auth === "offline") return <Login offline={auth === "offline"} />;
  return <Dashboard />;
}
