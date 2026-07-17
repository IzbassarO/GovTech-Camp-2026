"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Leaf, Menu, ShieldCheck, X } from "lucide-react";

const NAV = [
  { href: "/", label: "Обзор" },
  { href: "/analyze", label: "Анализ", prominent: true },
  { href: "/projects", label: "Проекты" },
  { href: "/methodology", label: "Методология" },
];

function Brand() {
  return (
    <Link href="/" className="flex items-center gap-3">
      <span className="flex h-9 w-9 flex-none items-center justify-center rounded-lg bg-accent-600">
        <Leaf className="h-5 w-5" aria-hidden />
      </span>
      <span className="leading-tight">
        <span className="block text-base font-semibold tracking-tight">Dalel</span>
        <span className="block text-[11px] font-medium uppercase tracking-wider text-slate-400">
          BizAI
        </span>
      </span>
    </Link>
  );
}

function EvidenceBadge() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-navy-700 bg-navy-800/80 px-2.5 py-1 text-[11px] font-medium text-accent-100">
      <ShieldCheck className="h-3.5 w-3.5 text-accent-500" aria-hidden />
      Evidence-first
    </span>
  );
}

export function SiteHeader() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  // Close the mobile panel on route change so it never lingers open.
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  return (
    <header className="sticky top-0 z-30 border-b border-navy-800 bg-navy-900 text-white">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-4">
          <Brand />
          <span className="hidden lg:inline-flex">
            <EvidenceBadge />
          </span>
        </div>

        <nav className="hidden items-center gap-1 sm:flex" aria-label="Основная навигация">
          {NAV.map((item) =>
            item.prominent ? (
              <Link
                key={item.href}
                href={item.href}
                className={`ml-1 rounded-lg px-3.5 py-2 text-sm font-semibold transition-colors ${
                  isActive(item.href)
                    ? "bg-accent-500 text-white"
                    : "bg-accent-600 text-white hover:bg-accent-500"
                }`}
                aria-current={isActive(item.href) ? "page" : undefined}
              >
                {item.label}
              </Link>
            ) : (
              <Link
                key={item.href}
                href={item.href}
                className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  isActive(item.href)
                    ? "bg-navy-800 text-white"
                    : "text-slate-300 hover:bg-navy-800 hover:text-white"
                }`}
                aria-current={isActive(item.href) ? "page" : undefined}
              >
                {item.label}
              </Link>
            ),
          )}
        </nav>

        <button
          type="button"
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg text-slate-200 hover:bg-navy-800 sm:hidden"
          aria-label={mobileOpen ? "Закрыть меню" : "Открыть меню"}
          aria-expanded={mobileOpen}
          aria-controls="mobile-nav-panel"
          onClick={() => setMobileOpen((v) => !v)}
        >
          {mobileOpen ? <X className="h-5 w-5" aria-hidden /> : <Menu className="h-5 w-5" aria-hidden />}
        </button>
      </div>

      {/* Absolutely positioned so opening it never shifts page layout below. */}
      {mobileOpen ? (
        <nav
          id="mobile-nav-panel"
          aria-label="Мобильная навигация"
          className="absolute inset-x-0 top-16 border-b border-navy-800 bg-navy-900 px-4 pb-4 pt-2 shadow-drawer sm:hidden"
        >
          <div className="flex flex-col gap-1">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                  item.prominent
                    ? isActive(item.href)
                      ? "bg-accent-500 font-semibold text-white"
                      : "bg-accent-600 font-semibold text-white hover:bg-accent-500"
                    : isActive(item.href)
                      ? "bg-navy-800 text-white"
                      : "text-slate-300 hover:bg-navy-800 hover:text-white"
                }`}
                aria-current={isActive(item.href) ? "page" : undefined}
              >
                {item.label}
              </Link>
            ))}
          </div>
          <div className="mt-3 border-t border-navy-800 pt-3">
            <EvidenceBadge />
          </div>
        </nav>
      ) : null}
    </header>
  );
}
