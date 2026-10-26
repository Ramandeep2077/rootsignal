"use client";

import { useSyncExternalStore } from "react";

type Theme = "system" | "light" | "dark";
const OPTIONS: Theme[] = ["system", "light", "dark"];

function read(): Theme {
  try {
    const value = localStorage.getItem("theme");
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

const listeners = new Set<() => void>();

function apply(theme: Theme) {
  try {
    if (theme === "system") localStorage.removeItem("theme");
    else localStorage.setItem("theme", theme);
  } catch {
    // storage unavailable (private mode): still apply for this page view
  }
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
  listeners.forEach((listener) => listener());
}

export function ThemeToggle() {
  const theme = useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    read,
    () => "system" as Theme,
  );
  return (
    <div role="radiogroup" aria-label="Theme" className="flex rounded-md border border-line p-0.5 text-xs">
      {OPTIONS.map((option) => (
        <button
          key={option}
          role="radio"
          aria-checked={theme === option}
          onClick={() => apply(option)}
          className={`rounded px-2 py-1 capitalize ${theme === option ? "bg-surface-2 text-ink" : "text-muted hover:text-ink"}`}
        >
          {option}
        </button>
      ))}
    </div>
  );
}
