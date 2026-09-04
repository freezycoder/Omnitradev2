import { ScannerPage } from "@/components/ScannerPage";
import { Suspense } from "react";

export default function LongTermPage() {
  return (
    <Suspense>
      <ScannerPage kind="long" />
    </Suspense>
  );
}
