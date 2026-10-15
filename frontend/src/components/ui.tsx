import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

export function Container({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`container-shell ${className}`}>{children}</div>;
}

export function ButtonLink({ children, href, variant = "dark", ...props }: ComponentProps<typeof Link> & { variant?: "dark" | "light" | "outline" }) {
  return <Link href={href} {...props} className={`button button-${variant} ${props.className ?? ""}`}>{children}<span aria-hidden="true">↗</span></Link>;
}

export function TextLink({ children, ...props }: ComponentProps<typeof Link>) {
  return <Link {...props} className={`text-link ${props.className ?? ""}`}>{children}<span aria-hidden="true"> ↗</span></Link>;
}

export function Status({ children }: { children: ReactNode }) {
  return <span className="status"><span aria-hidden="true" className="status-dot" />{children}</span>;
}

export function Notice({ title = "In preparation", children }: { title?: string; children: ReactNode }) {
  return <aside className="notice"><p className="eyebrow">{title}</p><p>{children}</p></aside>;
}

export function SectionHeading({ index, title, children }: { index: string; title: string; children?: ReactNode }) {
  return <div className="section-heading"><p className="eyebrow">{index}</p><div><h2>{title}</h2>{children && <p className="section-description">{children}</p>}</div></div>;
}

export function PageIntro({ eyebrow, title, children }: { eyebrow: string; title: string; children: ReactNode }) {
  return <header className="page-intro"><Container><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="intro-copy">{children}</p></Container></header>;
}

export function InfoCard({ number, title, children }: { number: string; title: string; children: ReactNode }) {
  return <article className="info-card"><span className="eyebrow">{number}</span><h3>{title}</h3><p>{children}</p></article>;
}

type FieldProps = { id: string; label: string; hint?: string } & ComponentProps<"input">;
export function FormField({ id, label, hint, ...props }: FieldProps) {
  return <div className="form-field"><label htmlFor={id}>{label}</label><input id={id} {...props} aria-describedby={hint ? `${id}-hint` : undefined} />{hint && <p id={`${id}-hint`} className="field-hint">{hint}</p>}</div>;
}

export function TextAreaField({ id, label, ...props }: { id: string; label: string } & ComponentProps<"textarea">) {
  return <div className="form-field"><label htmlFor={id}>{label}</label><textarea id={id} rows={5} {...props} /></div>;
}
