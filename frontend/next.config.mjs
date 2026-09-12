/** @type {import('next').NextConfig} */

// When building the desktop (Tauri) app we produce a fully static export that
// Tauri serves from its bundled webview. The regular web build is unchanged.
const isDesktop = process.env.OMNITRADE_DESKTOP === "1";

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "X-Permitted-Cross-Domain-Policies", value: "none" }
];

const nextConfig = {
  reactStrictMode: true,
  turbopack: {
    root: import.meta.dirname
  },
  ...(isDesktop
    ? {
        output: "export",
        trailingSlash: true,
        images: {
          unoptimized: true
        }
      }
    : {
        async headers() {
          return [{ source: "/:path*", headers: securityHeaders }];
        }
      })
};

export default nextConfig;
