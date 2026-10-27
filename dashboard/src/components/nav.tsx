import Link from "next/link";
import { Suspense } from "react";
import { NavLinks, StaticNavLinks } from "./nav-links";
import { ThemeToggle } from "./theme-toggle";

export function Nav() {
  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
        <Link href="/incidents" className="flex items-center gap-2 whitespace-nowrap font-semibold">
          <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full bg-accent" />
          RootSignal
        </Link>
        {/* The active-link highlight reads the URL, which is runtime data on dynamic routes. */}
        <Suspense fallback={<StaticNavLinks />}>
          <NavLinks />
        </Suspense>
        <div className="ml-auto">
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
