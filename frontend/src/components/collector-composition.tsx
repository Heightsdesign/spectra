import { BrandLogo } from "./brand-logo";

export function CollectorComposition() {
  return <figure className="collector-composition" aria-labelledby="collector-caption">
    <div className="collection-topline"><span>For the love of the collection.</span><span aria-hidden="true">01 / 03</span></div>
    <div className="collector-stage" role="img" aria-label="Three overlapping card silhouettes with vivid purple, yellow and orange framing and a green geometric detail. Illustrative artwork, not actual cards or SPECTRA products.">
      <div className="collector-orbit" aria-hidden="true" />
      <div className="collector-card card-back" aria-hidden="true"><div className="card-outline" /><span className="card-small-type">THE FIRST FIND.</span></div>
      <div className="collector-card card-middle" aria-hidden="true"><div className="card-outline" /><div className="card-window"><span className="card-circle" /></div><span className="card-small-type">THE LONG CHASE.</span></div>
      <div className="collector-card card-front" aria-hidden="true"><div className="card-topline"><BrandLogo variant="white" compact /><span>COLLECTION<br />STUDY / 03</span></div><div className="card-art"><span className="card-orb" /><span className="card-stripe" /><span className="card-art-cross">+</span></div><div className="card-bottomline"><span>WORTH A<br />CLOSER LOOK.</span><span>↗</span></div></div>
    </div>
    <figcaption id="collector-caption">Card silhouettes · Illustration only, not a SPECTRA product</figcaption>
  </figure>;
}
