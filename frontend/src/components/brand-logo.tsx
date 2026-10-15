import Image from "next/image";

export function BrandLogo({ variant = "black", compact = false }: { variant?: "black" | "white"; compact?: boolean }) {
  return <span className={`brand-logo ${compact ? "brand-logo-compact" : "brand-logo-full"}`}>
    <Image src={`/brand/spectra_logo_${compact ? "" : "full_"}${variant}_v2.png`} width={compact ? 1272 : 2024} height={compact ? 1272 : 2024} alt={compact ? "SPECTRA" : "SPECTRA card grading"} unoptimized />
  </span>;
}

