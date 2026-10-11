import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import TopNav from "./TopNav";
import DemoBar from "./DemoBar";
import { useAppState } from "../state/AppState";

/** Route → document title, so browser tabs and screen readers announce the page. */
const TITLES = [
  [/^\/scan\/[^/]+\/verify/, "Check the details"],
  [/^\/scan\/added\//, "Medication added"],
  [/^\/scan/, "Scan a pill bottle"],
  [/^\/history/, "History"],
  [/^\/settings/, "Settings"],
  [/^\//, "Home"],
];

export default function AppShell({ children }) {
  const { data, error, usingMock } = useAppState();
  const { pathname } = useLocation();
  const mainRef = useRef(null);

  useEffect(() => {
    const [, title] = TITLES.find(([re]) => re.test(pathname)) || [null, "MedCheck"];
    document.title = `${title} · MedCheck`;
    // SPA route change: move focus to the main landmark for screen readers.
    mainRef.current?.focus({ preventScroll: true });
  }, [pathname]);

  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-full focus:bg-white focus:px-4 focus:py-2"
      >
        Skip to content
      </a>
      <TopNav />
      <main
        id="main"
        ref={mainRef}
        tabIndex={-1}
        className={`mx-auto w-full max-w-7xl flex-1 px-4 pt-6 focus:outline-none sm:px-6 sm:pt-8 lg:px-8 xl:px-10 2xl:px-12 ${
          usingMock ? "pb-32" : "pb-16"
        }`}
      >
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
