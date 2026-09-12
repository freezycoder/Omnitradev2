import { EtfComparePage } from "@/components/EtfComparePage";
import { Suspense } from "react";

export default function EtfCompareRoute() {
  return (
    <Suspense>
      <EtfComparePage />
    </Suspense>
  );
}
