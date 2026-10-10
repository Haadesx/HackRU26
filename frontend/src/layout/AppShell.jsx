import TopNav from "./TopNav";
import DemoBar from "./DemoBar";
import { useAppState } from "../state/AppState";

export default function AppShell({ children }) {
  const { data, error, usingMock } = useAppState();
  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-full focus:bg-white focus:px-4 focus:py-2">
        Skip to content
      </a>
      <TopNav />
      <main id="main" className={`mx-auto max-w-6xl px-4 pt-8 sm:px-8 ${usingMock ? "pb-32" : "pb-16"}`}>
        {data ? children : (
          <p className="rounded-2xl bg-white p-6 text-ink-soft" role="status">
            {error ? `Can't reach the MedCheck hub (${error}). Check that it's running and VITE_API_URL is correct.` : "Loading Rosa's medications…"}
          </p>
        )}
      </main>
      {usingMock && data && <DemoBar />}
    </div>
  );
}
