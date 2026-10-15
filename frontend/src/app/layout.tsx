import type { Metadata } from "next";
import { Header } from "@/components/header";
import { Footer } from "@/components/footer";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "SPECTRA — Great cards deserve great attention", template: "%s | SPECTRA" },
  description: "Precision, transparency and care for the collectibles that matter to you. Discover SPECTRA’s approach to trading-card grading. Online submissions coming soon.",
  applicationName: "SPECTRA",
  icons: { icon: [
    { url: "/brand/spectra_logo_black_v2.png", type: "image/png", sizes: "1272x1272", media: "(prefers-color-scheme: light)" },
    { url: "/brand/spectra_logo_white_v2.png", type: "image/png", sizes: "1272x1272", media: "(prefers-color-scheme: dark)" },
  ], apple: "/brand/spectra_logo_black_v2.png" },
  robots: { index: false, follow: true },
  openGraph: { type: "website", siteName: "SPECTRA", locale: "en_GB", title: "SPECTRA — Great cards deserve great attention", description: "From childhood favourites to long-awaited finds. Precision, transparency and care for your collection. Online submissions coming soon." },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><a className="skip-link" href="#main-content">Skip to content</a><Header /><main id="main-content" tabIndex={-1}>{children}</main><Footer /></body></html>;
}
