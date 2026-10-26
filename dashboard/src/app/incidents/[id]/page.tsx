import type { Metadata } from "next";
import { Suspense } from "react";
import { DetailSkeleton, IncidentDetailView } from "@/components/incident-detail";

export const metadata: Metadata = { title: "Incident · oncall-copilot" };

// With Cache Components, route params are runtime data: the client view unwraps them inside Suspense.
export default function IncidentPage({ params }: PageProps<"/incidents/[id]">) {
  return (
    <Suspense fallback={<DetailSkeleton />}>
      <IncidentDetailView params={params} />
    </Suspense>
  );
}
