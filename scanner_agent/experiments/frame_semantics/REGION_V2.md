# Competing-frame region V2 — declared after Phase 1, before V2 evaluation

Phase 1: Tritox's three V1 leaders share right/bottom/left equations; only top
differs. Visual context identifies a name/HP header (~135 px), then an artwork
frame stripe (~12 px). Header RGB/luminance differs substantially from that stripe.
This motivates a conditional appearance-assignment diagnostic, not OCR or a
general decorative-border/artwork/text classifier. Historical manual results are
known to development; references are excluded from extraction and pair ordering.

New module only; preserve semantic V1, S2.1, S2.2a/b/c and all gates unchanged.
Compare existing geometries that differ on exactly one side. Do not compare
multi-side changes using invented context. Use normalized line equality to find
common sides, not IDs. The IDs label output only.

For each disputed strip, measure ORIGINAL integer RGB pixels between the two
lines over the physical side's usable span. Sample each unchanged side's native
2–8 px interior/exterior collars as contextual prototypes. Compare the disputed
strip's per-block RGB histogram distances to EACH of the three side prototypes.
16 bins/channel, marginal RGB mean total variation, 12 along-side blocks. Positive
`distance_to_exterior - distance_to_interior` supports treating the strip as
interior; negative supports exterior. A strip matching the surrounding band can
therefore favor the inward boundary. No candidate order, area, symmetry, manual
distance, or outermost prior enters the rule.

Emit a pairwise diagnostic preference only if, for all three contextual sides,
all leave-one-block-out median margins have the same strict sign, and that sign
is unchanged for all six sampling settings: 1/2/3 native-pixel boundary trims and
along spans [.18,.82] / [.22,.78]. Numerical sign tolerance 1e-10, not an accuracy
threshold. Every block needs >=16 native pixels and each context collar >=48;
otherwise report unavailable. No reweighting/tuning after observing results.

Record color/luminance percentiles and histograms; luminance standard deviation,
Gaussian sigma-1 high-pass RMS; native Sobel gradient magnitudes and edge density
at 8/16/32 gray/pixel; 18-bin unoriented edge-tangent angle distribution relative
to the physical side; and per-block distributions. Luminance is the fixed RGB
code-value projection [.2126,.7152,.0722], not calibrated luminance. Sobel uses
scale 1/8. These thresholds describe texture, never gate acceptance or determine
the appearance preference. All derivatives and smoothing are derived arrays.

Report graph relations separately from validity. A conditional region-model
leader requires an untruncated search and a reliable direct pairwise win over
every other hypothesis in the evaluated comparison set. Compute both all valid
hypotheses and the pre-existing V1 nondominated subset; a leader only within that
subset is labelled as such, never a complete-search semantic selection. Missing
comparisons, mixed evidence and cycles retain abstention.

Evaluate every existing S2.2b validation report, deduplicating original SHA only
for cross-capture counts. Use V1's existing reliable registration/associations for
stability diagnostics, never reference geometry. Read the manual comparison only
after region outputs are written. Existing non-Tritox captures with zero complete
hypotheses remain explicitly unavailable, not negative examples or successful
semantic detections. No absolute accuracy or grading promotion.

Run from scanner_agent with the existing analysis environment; output must be new:

```powershell
.\.venv-analysis\Scripts\python.exe -B -m spectra_frame_evaluation.semantic_region_validation --v1-manifest local_data\s2_2b-semantic-exp1\20261019-v1\final-evaluation\evaluation.json --output local_data\NEW_REGION_V2 --reference-comparison local_data\s2_2c\compare\20261019T143930_50e17bd14131403588f099c16d729a38\report.json
```

The optional reference-comparison argument is consumed only after region outputs
and their inventory have been written. V1 results are read, never rewritten.
