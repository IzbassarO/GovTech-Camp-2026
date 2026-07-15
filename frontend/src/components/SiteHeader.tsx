"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Leaf } from "lucide-react";

const NAV = [
  { href: "/", label: "Обзор" },
  { href: "/projects", label: "Проекты" },
  { href: "/methodology", label: "Методология" },
];

export function SiteHeader() {
  const pathname = usePathname();

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <header className="sticky top-0 z-30 border-b border-navy-800 bg-navy-900 text-white">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <Link href="/" className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-600">
            <Leaf className="h-5 w-5" aria-hidden />
          </span>
          <span className="leading-tight">
            <span className="block text-base font-semibold tracking-tight">Dalel</span>
            <span className="block text-[11px] font-medium uppercase tracking-wider text-slate-400">
              BizAI
            </span>
          </span>
        </Link>

        <nav className="flex items-center gap-1" aria-label="Основная навигация">
          {NAV.map((item) => (
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
          ))}
        </nav>
      </div>
    </header>
  );
}
