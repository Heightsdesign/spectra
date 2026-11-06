# S2.2b semantic compatibility experiment V1

Predeclared before evaluating semantic ranks (2026-10-19). This is an additive
diagnostic module, not a modification of S2.2b 0.1.0 validity/selection. It reads
original pixels and existing four-line hypotheses. No reference enters extraction
or ordering. All outcomes remain review_required, automatic_acceptance false.

Four equally unprivileged descriptor objectives (no weighted score):

1. Transition continuity: minimum across four sides of mean cosine agreement
   between local RGB transition vectors and the side's median transition vector.
   Negative cosine contributes zero; zero-strength transitions contribute zero.
2. Narrow exterior collar photometric consistency: one minus maximum pairwise
   side RGB histogram total-variation distance.
3. Global printed-band compatibility: one minus maximum pairwise side histogram
   distance in corridors between the physical sides and proposed frame. This is
   an appearance hypothesis about a shared enclosing band, not proof of semantics.
4. Interior/exterior distinction: minimum four-side histogram distance between
   narrow collars on either side of the proposed frame.

Marginal RGB histograms: 16 fixed equal bins/channel, mean channel total variation;
not calibrated color or a joint texture model. Narrow collars sample 2/4/8 native
pixels away. Global corridors sample 16 positions at 10–90% of the distance from
physical side to candidate. 96 along-side locations span the existing configured
corner exclusion. Report band color spread, local transition strength/direction,
along-side variability and collar/corridor distributions separately.

Rank by Pareto fronts only: dominate means at least as good on all four objectives
and strictly better on one (1e-10 numerical tolerance, not an accuracy threshold).
Never break incomparable ties by ID, candidate order, area, margins, symmetry,
reference error or outermost position. Repeat with normal phases -0.5/0/+0.5 px
and even/odd profile subsets (nine views including full profiles). A diagnostic
preference requires the same single Pareto leader in every view, at least two
valid hypotheses, complete domain sampling and an untruncated existing search.
No preferred hypothesis is a selected/accepted physical or printed frame.

False-positive controls include visually indistinguishable nested structures and
uniform images. RGB appearance cannot universally identify design intent. A
coherent artwork rectangle may win these descriptors; exposed manual reference
agreement on one card cannot certify semantics or accuracy.

Cross-capture stability is descriptive, never added to the ordering. Group only
captures sharing the exact upstream series identifier; validate interior-print
SIFT registration, ratio .70, RANSAC 2 px, >=30 inliers, >=40% x/y landmark span
of anchor physical bounding box, and interleaved holdout p95 <=2.5 px. These are
new diagnostic association guards, not changes to any existing gate. Match
hypotheses by mutual nearest transformed corners over cyclic side mappings, max
corner discrepancy <=5 px, with runner-up distance gap > twice holdout p95.
Otherwise report unavailable/ambiguous. No forced association or reference use.

Evaluate every existing validation S2.2b report; deduplicate identical
image/report semantics for cross-capture counts. References are loaded only in a
separate post-scoring evaluation phase. Do not tune this specification to Tritox.
