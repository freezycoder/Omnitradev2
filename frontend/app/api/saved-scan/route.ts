import globalScan from "@/data/global-scan.json";
import internationalScan from "@/data/international-scan.json";
import { applyScanFreshnessPolicy } from "@/lib/api";
import type { ScanPayload } from "@/lib/api";


export const dynamic = "force-dynamic";


export async function GET(request: Request) {
  const universe = new URL(request.url).searchParams.get("universe") ?? "global";
  if (universe !== "global" && universe !== "international") {
    return Response.json(
      { error: "universe must be global or international" },
      { status: 400 }
    );
  }

  const savedScan = (universe === "international" ? internationalScan : globalScan) as ScanPayload;
  return Response.json(applyScanFreshnessPolicy(savedScan, "cached_real"), {
    headers: { "Cache-Control": "no-store" }
  });
}
