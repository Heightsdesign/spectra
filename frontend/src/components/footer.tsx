import Link from 'next/link';
import { Container } from './ui';

export function Footer() {
  return <footer className="site-footer"><Container>
    <div className="footer-top"><div><Link href="/" className="brand-home" aria-label="SELBY"><span className="selby-wordmark">SELBY</span></Link><p>For the first pull.<br />For the lifelong collection.</p></div>
      <nav aria-label="Footer navigation"><Link href="/services">Services <span aria-hidden="true">↗</span></Link><Link href="/standards">Standards <span aria-hidden="true">↗</span></Link><Link href="/how-it-works">The process <span aria-hidden="true">↗</span></Link><Link href="/verify">Certificate verification <span aria-hidden="true">↗</span></Link><Link href="/contact">Contact <span aria-hidden="true">↗</span></Link></nav>
      <div className="footer-note"><p className="eyebrow">SELBY</p><p>Precision. Transparency. Care.</p></div>
    </div><div className="footer-bottom"><p>© {new Date().getFullYear()} SELBY</p><p>Card grading</p></div>
  </Container></footer>;
}
