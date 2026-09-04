import { ScannerPage } from "@/components/ScannerPage";
import { Suspense } from "react";

export default function InternationalPage() {
  return (
    <Suspense>
      <ScannerPage kind="international" />
    </Suspense>
  );
}
