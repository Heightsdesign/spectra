import { CollectorComposition } from "@/components/collector-composition";
import { ButtonLink, Container, InfoCard, SectionHeading, Status, TextLink } from "@/components/ui";
import { categories, steps } from "@/lib/content";

export default function Home() {
  return <>
    <section className="hero"><Container>
      <div className="hero-topline"><p className="eyebrow">Trading-card grading · France</p><Status>Preparing for launch</Status></div>
      <div className="hero-grid"><div className="hero-copy"><h1>Great cards<br /> deserve <span>great<br /> attention.</span></h1><p>From the cards you grew up with to the ones you&apos;ve spent years chasing. SPECTRA brings precision, transparency and care to the collectibles that matter to you.</p><ButtonLink href="/how-it-works">Submit cards</ButtonLink><p className="cta-note">Online submissions coming soon</p></div>
      <CollectorComposition /></div>
      <div className="hero-foot"><span>For the keepers. The chase cards. The stories.</span><a href="#philosophy" className="text-link">Explore our approach <span aria-hidden="true">↓</span></a></div>
    </Container></section>
    <section id="philosophy" className="section"><Container><SectionHeading index="01 / Our philosophy" title="The card comes first." />
      <div className="editorial-split"><p className="statement">A grade should make<br />condition easier<br />to understand.</p><div className="prose"><p>The first pull. The trade you still remember. The card you finally tracked down. Every collection has its stories. Our approach starts with the same care: looking closely, describing clearly and recognizing the limits of what an image can tell us.</p><p>We are developing a computer-assisted assessment process with human validation of final grades. Technology supports observation; judgment remains a responsibility.</p><TextLink href="/standards">Read our grading philosophy</TextLink></div></div>
    </Container></section>
    <section className="section section-soft"><Container><SectionHeading index="02 / The details" title="Four areas. One considered view.">From a childhood favourite to a long-awaited find: four ways to look closer at what makes each card yours.</SectionHeading><div className="info-grid">{categories.map(c => <InfoCard key={c.number} number={c.number} title={c.title}>{c.description}</InfoCard>)}</div><p className="section-footnote">The final grading scale, category weighting and assessment thresholds are still being defined.</p></Container></section>
    <section className="section"><Container><SectionHeading index="03 / The process" title="From your collection. And back.">A preview of the planned submission journey. Online submissions are not yet available.</SectionHeading><ol className="process-list">{steps.map(step => <li key={step.number}><span className="eyebrow">{step.number}</span><h3>{step.title}</h3><p>{step.description}</p></li>)}</ol><TextLink href="/how-it-works">Understand the process</TextLink></Container></section>
    <section className="section section-dark"><Container><SectionHeading index="04 / Trust & transparency" title="Clarity is a standard worth setting." /><div className="editorial-split"><p className="statement">Clear criteria.<br />Human responsibility.<br />No shortcuts.</p><div className="prose"><p>Our commitment is to explain how an assessment is reached, distinguish observation from certainty, and make the scope of a service clear before you submit.</p><p>Published standards, service terms and certificate verification are planned for launch. They are not available services today.</p><ButtonLink href="/standards" variant="light">Explore our standards</ButtonLink></div></div></Container></section>
  </>;
}
