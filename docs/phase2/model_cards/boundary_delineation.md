# Model Card — Model A, boundary delineation (SRS §3.4.1)

> **This card documents a model that does not exist.** Master §2 rule 5 requires
> every model to ship with its card; ADR-0013 records why Model A is not built.
> The card is written anyway, in full, for two reasons. A card first attempted
> under gate pressure is a card nobody has tested. And the *contract* around this
> model — the IoU gate, the admission rule, the area-mismatch flag — **is**
> built and tested, so the thing that most needs recording is precisely what a
> Track B team must supply to make the contract mean anything.

## 1. Identification

| Field | Value |
|---|---|
| Model name / version | `boundary_delineation` — **unbuilt** |
| Reference method | SAM ([Kirillov et al., arXiv:2304.02643](https://arxiv.org/abs/2304.02643)) or U-Net ([arXiv:1505.04597](https://arxiv.org/abs/1505.04597)), fine-tuned per Phase 2 §4 WS-2.2 |
| Registry stage | None — nothing registered |
| Model tier | Tier 1 if it ever reaches an underwriter: its output drives a fraud flag |
| Owner (accountable) | Geospatial DS squad lead |
| Developer (R) | Geospatial DS |
| Independent validator | **Not assigned.** Master §3.1 requires a validator who is not the developer; there is no model to validate |
| Date registered | Not registered |

## 2. Why it is not built

Three independent blockers, any one of which is sufficient:

1. **No imagery.** `datasets/` holds three tabular credit datasets and no raster.
   Sentinel-2 and Sentinel-1 are freely available, but a scene stack over a
   bank's operating districts across three seasons is terabytes, and the phase
   card requires overlapping a full crop season — a calendar constraint no
   engineering removes.
2. **No labels.** Fine-tuning needs officer GPS-walk polygons (**LH-407**), and
   Phase 2 §8 forbids any polygon not observed or walked, which makes the walk
   set the *only* admissible label source. Collecting it is field work with a
   season's lead time, and no workstream in the programme plan schedules it.
3. **Master §2 rule 2.** The rule permits using the named library or porting it
   with unit tests reproducing its outputs on fixture data. Neither branch is
   available: there is no imagery to reproduce outputs on, and a stdlib
   re-derivation of a fine-tuned foundation model would be a different model
   wearing the paper's name — worse than absence, because it would look like
   Model A on a deliverables checklist.

## 3. What is built, and what it obliges Track B to supply

| Built (`lending_hub.agri.boundary`, `agri.geometry`) | What the model must supply |
|---|---|
| `evaluate_gate()` — median IoU with p25, p10 and the below-gate share | Delineations paired with held-out walked polygons |
| `admissible()` — the per-plot rule: gate passed AND this boundary's confidence >= gate | A **per-boundary confidence calibrated against IoU** (see §5) |
| `area_flag()` — the >20% claimed-vs-observed fraud signal, with direction | A boundary that cleared the gate |
| `snap_to_cadastral()` — best-match snapping with a floor | Digitised cadastral parcels, and a ratified `min_iou` |
| `Delineation.to_plot()` — the only path into the registry, stamping `AUTO_DELINEATED` | — |

## 4. Gate

Phase 2 §4: **median IoU >= 0.75** against held-out GPS-walk polygons, before
auto-delineations are shown at all. Below it, plots require a manual walk.

`MIN_GATE_SAMPLE = 100` is **not from the phase file** and is a finding: the
phase file states a threshold with no sample size, and "median 0.78" reads
identically whether it came from 12 plots or 1,200. A median over a dozen plots
has a confidence interval that spans the gate in both directions.

## 5. Known limitations of the contract as specified

**The gate is established on IoU and applied through confidence.** At inference
there is no walked polygon to compare against — that is the whole difficulty —
so the gate is measured on held-out walked plots and then enforced through the
model's own confidence score. That substitution holds only while confidence is
calibrated against IoU, which is a **validation obligation on whoever builds the
model**, not a property any score has by default. An uncalibrated confidence
makes `admissible()` a filter on an arbitrary number.

**A passing median hides a failing tail.** Delineation fails on small, irregular
and intercropped fields — which is to say on the smallest borrowers. A median of
0.80 is compatible with a quarter of plots below 0.5. `GateResult` carries p25,
p10 and the below-gate share so this reaches whoever signs the gate; the phase
file asks only for the median.

**The area flag is a fraud signal built on a model output.** Flagging a borrower
for fraud on the basis of a delineation the model was itself unsure about is the
worst outcome available in this workstream. `area_flag()` cannot check the
provenance of the polygon it is given; the obligation sits with the caller and
is stated in the function's docstring.

## 6. Fairness

Not assessed — there is no model. The geographic disparate-impact question this
model contributes to is measured by `agri.disparate` and blocked on **LH-410**
(the ratified comparison units and disparity bar). Note the specific risk here:
delineation quality varies with field size and shape, so a boundary model's
error is correlated with smallholding, and an IoU gate applied uniformly excludes
the smallest farmers from auto-delineation at a higher rate than the largest.

## 7. Monitoring, promotion, rollback

None. Nothing to monitor, and `lending_hub.mlops.promotion` would refuse the
transition on the absent-validator basis alone (Master §3.1).

## 8. Open tickets

**LH-407** (GPS-walk polygon set) · **LH-409** (where a below-gate plot's manual
walk is actually routed, and within what SLA) · **LH-406** (the agri portfolio) ·
**LH-120** (data-sharing approvals).

## 9. Sign-off

| Role | Name | Date |
|---|---|---|
| Developer | — | — |
| Independent validator | — | — |
| Model Risk | — | — |

**Unsigned, and correctly so:** there is no model to validate.
