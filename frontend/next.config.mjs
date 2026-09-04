/** @type {import('next').NextConfig} */

// When building the desktop (Tauri) app we produce a fully static export that
// Tauri serves from its bundled webview. The regular web build is unchanged.
const isDesktop = process.env.OMNITRADE_DESKTOP === "1";

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
    : {})
};

export default nextConfig;
