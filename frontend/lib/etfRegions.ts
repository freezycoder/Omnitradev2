export type EtfListingRegionKey = "us" | "europe" | "asia_pacific";

export type EtfListingRegion = {
  key: EtfListingRegionKey;
  label: string;
  short_label: string;
  description: string;
  universe_name: string;
  ticker_count?: number;
};

export const DEFAULT_ETF_REGION: EtfListingRegionKey = "us";
export const ETF_REGION_STORAGE_KEY = "omnitrade.etfListingRegion";

export const ETF_LISTING_REGIONS: EtfListingRegion[] = [
  {
    key: "us",
    label: "United States",
    short_label: "US",
    description: "US-listed ETFs for US brokerage accounts. EU/EEA retail accounts typically cannot buy these share classes.",
    universe_name: "Liquid US-listed ETFs"
  },
  {
    key: "europe",
    label: "Europe (UCITS)",
    short_label: "Europe",
    description: "UCITS ETFs listed on Xetra, London, and Euronext Amsterdam for EU/EEA and UK retail accounts.",
    universe_name: "Liquid Europe-listed UCITS ETFs"
  },
  {
    key: "asia_pacific",
    label: "Asia-Pacific",
    short_label: "Asia-Pacific",
    description: "ETFs listed in Tokyo, Hong Kong, and Australia.",
    universe_name: "Liquid Asia-Pacific listed ETFs"
  }
];

export const ETF_UNIVERSE_US = [
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
] as const;

export const ETF_UNIVERSE_EUROPE = [
  "VWCE.DE",
  "VWRA.L",
  "VWRL.L",
  "EUNL.DE",
  "IWDA.AS",
  "SWDA.L",
  "IUSQ.DE",
  "XDWD.DE",
  "SXR8.DE",
  "CSPX.L",
  "VUAA.L",
  "VUSA.L",
  "SPY5.DE",
  "SXRV.DE",
  "EQQQ.L",
  "EXW1.DE",
  "EXS1.DE",
  "EXSA.DE",
  "IMAE.AS",
  "ISF.L",
  "IS3N.DE",
  "EIMI.L",
  "VFEM.L",
  "EMIM.L",
  "AGGU.L",
  "IEAC.L",
  "VAGF.DE",
  "SGLN.L",
  "4GLD.DE",
  "XEON.DE",
  "XAIX.DE",
  "IUIT.L",
  "INRG.L",
  "IUSN.DE",
  "ZPRV.DE",
  "ZPRX.DE"
] as const;

export const ETF_UNIVERSE_ASIA_PACIFIC = [
  "1306.T",
  "1321.T",
  "1348.T",
  "1578.T",
  "1655.T",
  "2558.T",
  "2631.T",
  "2800.HK",
  "2823.HK",
  "2828.HK",
  "3033.HK",
  "3188.HK",
  "STW.AX",
  "VAS.AX",
  "VGS.AX",
  "VTS.AX",
  "IVV.AX",
  "NDQ.AX",
  "A200.AX",
  "IOZ.AX",
  "IEM.AX",
  "GOLD.AX",
  "QUAL.AX",
  "ETHI.AX",
  "BGBL.AX"
] as const;

export const ETF_STATIC_SYMBOLS = [
  ...ETF_UNIVERSE_US,
  ...ETF_UNIVERSE_EUROPE,
  ...ETF_UNIVERSE_ASIA_PACIFIC
];

const REGION_ALIASES: Record<string, EtfListingRegionKey> = {
  usa: "us",
  united_states: "us",
  unitedstates: "us",
  eu: "europe",
  eea: "europe",
  uk: "europe",
  ucits: "europe",
  apac: "asia_pacific",
  asia: "asia_pacific",
  asia_pac: "asia_pacific",
  asiapacific: "asia_pacific",
  jp: "asia_pacific",
  hk: "asia_pacific",
  au: "asia_pacific"
};

export function normalizeEtfRegion(value: string | null | undefined): EtfListingRegionKey {
  const key = String(value || DEFAULT_ETF_REGION)
    .trim()
    .toLowerCase()
    .replaceAll("-", "_")
    .replaceAll(" ", "_");
  const aliased = REGION_ALIASES[key] ?? key;
  if (aliased === "us" || aliased === "europe" || aliased === "asia_pacific") {
    return aliased;
  }
  return DEFAULT_ETF_REGION;
}

export function etfRegionLabel(region: string | null | undefined): EtfListingRegion {
  const key = normalizeEtfRegion(region);
  return ETF_LISTING_REGIONS.find((item) => item.key === key) ?? ETF_LISTING_REGIONS[0];
}

export function readStoredEtfRegion(): EtfListingRegionKey | null {
  if (typeof window === "undefined") return null;
  try {
    return normalizeEtfRegion(window.localStorage.getItem(ETF_REGION_STORAGE_KEY));
  } catch {
    return null;
  }
}

export function storeEtfRegion(region: EtfListingRegionKey): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(ETF_REGION_STORAGE_KEY, region);
  } catch {
    // Ignore private-mode storage failures.
  }
}
