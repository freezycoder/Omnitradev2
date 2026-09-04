import { TickerAnalysisPage } from "@/components/TickerAnalysisPage";
import { Suspense } from "react";

export default function TickerPage() {
  return (
    <Suspense>
      <TickerAnalysisPage />
    </Suspense>
  );
}
