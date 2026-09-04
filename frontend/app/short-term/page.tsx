import { ScannerPage } from "@/components/ScannerPage";
import { Suspense } from "react";

export default function ShortTermPage() {
  return (
    <Suspense>
      <ScannerPage kind="short" />
    </Suspense>
  );
}
