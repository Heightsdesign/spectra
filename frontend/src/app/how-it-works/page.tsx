import type { Metadata } from "next";
import { Container, Notice, PageIntro, Status, TextLink } from "@/components/ui";
import { steps } from "@/lib/content";
export const metadata: Metadata = { title: "The submission process", description: "Preview the planned SPECTRA submission journey. Online submissions are coming soon; no orders or payments are currently accepted." };

export default function Process() {
  return <><PageIntro eyebrow="The process / Submission preview" title="Your collection. The next chapter.">Thinking about grading a favourite card? Here is the journey we are preparing, from getting it ready to welcoming it back.</PageIntro><section className="section"><Container><Status>Online submissions coming soon</Status><ol className="journey-list">{steps.map(step => <li key={step.number}><span className="journey-number">{step.number}</span><div><h2>{step.title}</h2><p>{step.description}</p></div></li>)}</ol><Notice title="Not accepting submissions">This is a preview of the intended process. There is no online submission form, checkout or shipping address yet. Please do not send cards until official instructions, eligibility and service terms have been published.</Notice><div className="prose"><p>Preparation requirements, delivery responsibilities, assessment stages and return arrangements remain subject to confirmation.</p><TextLink href="/services">See service information</TextLink></div></Container></section></>;
}
