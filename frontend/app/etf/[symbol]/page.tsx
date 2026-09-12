import { EtfAnalysisPage } from "@/components/EtfAnalysisPage";
import { Suspense } from "react";

export default function EtfSymbolPage() {
  return (
    <Suspense>
      <EtfAnalysisPage />
    </Suspense>
  );
}
