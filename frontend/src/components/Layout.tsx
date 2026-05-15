import { NavLink, Outlet } from "react-router-dom";
import { cn } from "@/lib/utils";

const TABS: { to: string; label: string }[] = [
  { to: "/", label: "Dashboard" },
  { to: "/audit", label: "Audit" },
  { to: "/rules", label: "Rules" },
];

export function Layout() {
  return (
    <div className="flex min-h-screen flex-col bg-slate-50 font-sans text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-6 px-6">
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-semibold tracking-tight text-axon-navy">
              AXON
            </span>
            <span className="text-xs uppercase tracking-[0.18em] text-slate-500">
              Console
            </span>
          </div>
          <nav className="flex items-center gap-1">
            {TABS.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                end={t.to === "/"}
                className={({ isActive }) =>
                  cn(
                    "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                    isActive
                      ? "bg-axon-navy/10 text-axon-navy"
                      : "text-slate-500 hover:bg-slate-100 hover:text-slate-900",
                  )
                }
              >
                {t.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
