"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Container } from "./ui";
import { BrandLogo } from "./brand-logo";

const links = [
  ["/services", "Services"], ["/standards", "Standards"],
  ["/how-it-works", "The process"], ["/verify", "Verify"], ["/contact", "Contact"],
  ["/account", "Account"],
] as const;

export function Header() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  return <header className="site-header"><Container className="header-inner">
    <Link className="brand-home" href="/" aria-label="SPECTRA home" onClick={() => setOpen(false)}><BrandLogo /></Link>
    <button type="button" className="menu-toggle" aria-expanded={open} aria-controls="primary-navigation" onClick={() => setOpen(!open)}>{open ? "Close −" : "Menu +"}</button>
    <nav id="primary-navigation" aria-label="Main navigation" className={open ? "primary-nav is-open" : "primary-nav"}>
      {links.map(([href, label]) => <Link key={href} href={href} aria-current={pathname === href ? "page" : undefined} onClick={() => setOpen(false)}>{label}</Link>)}
    </nav>
  </Container></header>;
}
