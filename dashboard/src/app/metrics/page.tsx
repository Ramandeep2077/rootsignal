import type { Metadata } from "next";
import { MetricsView } from "@/components/metrics-view";

export const metadata: Metadata = { title: "Metrics · oncall-copilot" };

export default function MetricsPage() {
  return <MetricsView />;
}
