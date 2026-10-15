import { ButtonLink, Container } from "@/components/ui";
export default function NotFound() {
  return <section className="section"><Container><p className="eyebrow">404 / Page not found</p><h1 className="error-title">A different direction.</h1><p className="intro-copy">The page you’re looking for isn’t available.</p><ButtonLink href="/">Return to SPECTRA</ButtonLink></Container></section>;
}
