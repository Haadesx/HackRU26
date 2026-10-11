import { NavLink } from "react-router-dom";
import HubStatus from "./HubStatus";

const TABS = [
  { to: "/", label: "Home", end: true },
  { to: "/scan", label: "Scan" },
  { to: "/track", label: "Track" },
  { to: "/history", label: "History" },
  { to: "/settings", label: "Settings" },
];

export default function TopNav() {
  return (
    <header className="border-b border-line bg-white">
      <nav aria-label="Main" className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-8">
        <div className="flex flex-wrap items-center gap-4 sm:gap-8">
          <NavLink to="/" className="flex items-center gap-2 text-xl font-bold text-navy">
            <span aria-hidden="true" className="h-4 w-8 rounded-full bg-gradient-to-r from-sky to-ice shadow-[inset_0_2px_0_rgba(255,255,255,.6)]" />
            MedCheck
          </NavLink>
          <ul className="flex flex-wrap gap-1">
            {TABS.map((t) => (
              <li key={t.to}>
                <NavLink
                  to={t.to}
                  end={t.end}
                  className={({ isActive }) =>
                    `inline-flex min-h-[44px] items-center rounded-full px-4 ${
                      isActive ? "bg-gradient-to-r from-[#D6E7F9] to-mist font-bold text-navy" : "text-ink-soft hover:bg-page"
                    }`
                  }
                >
                  {t.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
        <HubStatus />
      </nav>
    </header>
  );
}
