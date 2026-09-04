import type { Metadata } from "next";
import { AppShell } from "@/components/AppShell";
import "@fontsource/bebas-neue/400.css";
import "@fontsource/barlow/400.css";
import "@fontsource/barlow/500.css";
import "@fontsource/barlow/600.css";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "OmniTrade",
  description: "Research and portfolio analytics for OmniTrade",
  applicationName: "OmniTrade",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      {
        url: "/brand/omnitrade-icon.png",
        sizes: "512x512",
        type: "image/png"
      }
    ],
    apple: [
      {
        url: "/brand/apple-touch-icon.png",
        sizes: "180x180",
        type: "image/png"
      }
    ]
  }
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
