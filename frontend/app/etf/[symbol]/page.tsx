import { ETF_STATIC_SYMBOLS } from "@/lib/etfRegions";
import { EtfAnalysisPage } from "@/components/EtfAnalysisPage";
import { Suspense } from "react";

export function generateStaticParams() {
  return ETF_STATIC_SYMBOLS.map((symbol) => ({ symbol }));
}

export default function EtfSymbolPage() {
  return (
    <Suspense>
      <EtfAnalysisPage />
    </Suspense>
  );
}
