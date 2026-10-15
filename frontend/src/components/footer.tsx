import Link from "next/link";
import { Container } from "./ui";
import { BrandLogo } from "./brand-logo";

export function Footer() {
  return <footer className="site-footer"><Container>
    <div className="footer-top"><div><Link href="/" className="brand-home" aria-label="SPECTRA home"><BrandLogo variant="white" /></Link><p>For the first pull.<br />For the lifelong collection.</p></div>
      <nav aria-label="Footer navigation"><Link href="/services">Services <span aria-hidden="true">↗</span></Link><Link href="/standards">Standards <span aria-hidden="true">↗</span></Link><Link href="/how-it-works">The process <span aria-hidden="true">↗</span></Link><Link href="/verify">Certificate verification <span aria-hidden="true">↗</span></Link><Link href="/contact">Contact <span aria-hidden="true">↗</span></Link></nav>
      <div className="footer-note"><p className="eyebrow">France · International outlook</p><p>Preparing for launch.<br />Online submissions are coming soon.</p></div>
    </div><div className="footer-bottom"><p>© {new Date().getFullYear()} SPECTRA</p><p>Public website preview · Services not yet open</p></div>
  </Container></footer>;
}
