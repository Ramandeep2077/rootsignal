"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/incidents", label: "Incidents" },
  { href: "/metrics", label: "Metrics" },
];

function Links({ active }: { active?: string }) {
  return (
    <nav className="flex gap-1 text-sm">
      {LINKS.map((link) => {
        const isActive = active !== undefined && (active === link.href || active.startsWith(`${link.href}/`));
        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={isActive ? "page" : undefined}
            className={`rounded-md px-3 py-1.5 ${isActive ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:bg-surface-2"}`}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function NavLinks() {
  const pathname = usePathname();
  return <Links active={pathname === "/" ? "/incidents" : pathname} />;
}

export function StaticNavLinks() {
  return <Links />;
}
