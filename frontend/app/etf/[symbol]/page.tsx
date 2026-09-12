import { EtfAnalysisPage } from "@/components/EtfAnalysisPage";
import { Suspense } from "react";

const ETF_STATIC_SYMBOLS = [
  "SPY",
  "VOO",
  "IVV",
  "VTI",
  "QQQ",
  "IWM",
  "DIA",
  "XLK",
  "XLF",
  "XLE",
  "XLV",
  "XLY",
  "XLP",
  "XLI",
  "XLU",
  "XLB",
  "XLRE",
  "XLC",
  "EFA",
  "EEM",
  "VEA",
  "VWO",
  "IEMG",
  "AGG",
  "BND",
  "TLT",
  "IEF",
  "LQD",
  "HYG",
  "GLD",
  "SLV",
  "USO",
  "DBC",
  "SMH",
  "XBI",
  "ARKK",
  "IWF",
  "IWD",
  "MTUM",
  "QUAL",
  "USMV"
];

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
