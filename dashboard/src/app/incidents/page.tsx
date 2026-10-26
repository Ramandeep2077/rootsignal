import type { Metadata } from "next";
import { IncidentList } from "@/components/incident-list";

export const metadata: Metadata = { title: "Incidents · oncall-copilot" };

export default function IncidentsPage() {
  return <IncidentList />;
}
