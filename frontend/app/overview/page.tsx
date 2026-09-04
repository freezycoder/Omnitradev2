import { ScannerPage } from "@/components/ScannerPage";
import { Suspense } from "react";

export default function OverviewPage() {
  return (
    <Suspense>
      <ScannerPage kind="overview" />
    </Suspense>
  );
}
