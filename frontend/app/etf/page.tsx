import { EtfScreenerPage } from "@/components/EtfScreenerPage";
import { Suspense } from "react";

export default function EtfPage() {
  return (
    <Suspense>
      <EtfScreenerPage />
    </Suspense>
  );
}
