import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, usingMock } from "../api/client";

const Ctx = createContext(null);

export function AppStateProvider({ children }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [connected, setConnected] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const s = await api.getState();
      setData(s);
      setConnected(true);
      setError(null);
    } catch (e) {
      setConnected(false);
      setError(e.message);
    }
  }, []);

  /** Run an API call that returns the new state, and store it. Re-throws so callers can show errors in place. */
  const run = useCallback(async (fn) => {
    const next = await fn();
    if (next && next.medications) setData(next);
    return next;
  }, []);

  useEffect(() => {
    refresh();
    if (usingMock) return undefined;
    const t = setInterval(refresh, 4000); // doses logged by the wearable appear live
    return () => clearInterval(t);
  }, [refresh]);

  const value = useMemo(() => ({ data, error, connected, refresh, run, usingMock }), [data, error, connected, refresh, run]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAppState() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAppState must be used inside AppStateProvider");
  return v;
}
