import { describe, expect, it } from "vitest";
import { formatCompact, formatDuration, formatPercent, formatRelative, formatUsd, humanize } from "@/lib/format";

describe("format", () => {
  it("formats durations at every scale", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(0.25)).toBe("250 ms");
    expect(formatDuration(7.04)).toBe("7.0 s");
    expect(formatDuration(42)).toBe("42 s");
    expect(formatDuration(225.3)).toBe("3m 45s");
    expect(formatDuration(120)).toBe("2m");
  });

  it("formats relative times", () => {
    const now = Date.parse("2026-01-01T12:00:00Z");
    expect(formatRelative("2026-01-01T11:59:58Z", now)).toBe("just now");
    expect(formatRelative("2026-01-01T11:58:00Z", now)).toBe("2m ago");
    expect(formatRelative("2026-01-01T09:00:00Z", now)).toBe("3h ago");
  });

  it("formats numbers, money and labels", () => {
    expect(formatCompact(12900)).toBe("12.9K");
    expect(formatPercent(95.6043, 1)).toBe("95.6%");
    expect(formatUsd(0)).toBe("$0.00");
    expect(formatUsd(0.0042)).toBe("$0.0042");
    expect(humanize("PENDING_APPROVAL")).toBe("Pending approval");
  });
});
