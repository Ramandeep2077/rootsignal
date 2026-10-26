import { API_URL } from "@/lib/api";

export function ErrorBanner({ error }: { error: Error }) {
  return (
    <div role="alert" className="flex items-start gap-2 rounded-lg border border-line bg-surface px-4 py-3 text-sm">
      <span aria-hidden className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-critical" />
      <div>
        <p className="font-medium">Can&apos;t reach the alert service</p>
        <p className="text-ink-2">
          {error.message}. Expected it at <code className="font-mono text-xs">{API_URL}</code> — is{" "}
          <code className="font-mono text-xs">make up</code> running?
        </p>
      </div>
    </div>
  );
}
