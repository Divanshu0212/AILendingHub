# Phase 2 — where the data would come from

[ADR-0013](../adr/0013-phase2-agri-track.md) established Phase 2 on Track A only,
on the grounds that no public data substitutes for what the phase needs. **That
was too broad, and this document corrects it.** A dataset search conducted after
the build found that one of the three "categorically unsatisfiable" blockers has
a real, licensed, Indian public dataset behind it, and two others have partial
substitutes that were not looked for.

The correction matters because the two failure modes are different. Saying "no
data exists" when a dataset does exist is how a phase stays blocked for a year
on a sourcing problem somebody could have solved in an afternoon. Saying "this
dataset will do" when it will not is how a model gets trained on the wrong
country's crops. Each row below is therefore marked with what it can and cannot
carry, and every claim about size, licence and availability was **checked by
downloading or requesting the resource**, not read off a description.

Last checked: 2026-09-01.

---

## 1. Summary — what changed

| Phase 2 need | ADR-0013 said | Actually available | Verdict |
|---|---|---|---|
| Field boundaries for Model A | no labels, LH-407 | **Fields of The World — India: 10,000 hand-delineated Indian fields, CC-BY-4.0, one 7.8 MB parquet** | **Track P is now possible** for Model A |
| Crop labels for Model B | no ground truth | CropHarvest: 95,186 global labels, but **only 34 crop-typed points in India** | **Still blocked** — measured, not assumed |
| District yield for Model C | no statistics | ICRISAT DLD: district area/production/yield, 20 crops, 1966–2015-16 | **Available**, but portal-gated (§4) |
| Weather / SPEI | not addressed | CHIRPS, ERA5, and published SPEI grids for India | **Available** |
| Mandi prices | LH-408 | Agmarknet via data.gov.in API; CEDA historical archive | **Feed available**, LH-408 unchanged (§6) |
| Agri loan outcomes | LH-406 | RBI publishes **aggregates only**; no loan-level agri data anywhere public | **Structurally blocked** — confirmed |
| Imagery | terabytes, infeasible | Pre-extracted pixel time series exist; full scenes not needed | **Overstated in ADR-0013** (§7) |

**Net effect on the gate: nothing.** All six exit criteria remain not measurable,
because every one of them depends on LH-406 or LH-102, and neither moved. What
changed is the *reason* three of them are blocked, and that distinction is the
whole point of keeping "not measured" and "not measurable" apart.

---

## 2. Model A — field boundaries: this one is solvable now

**[Fields of The World](https://fieldsofthe.world/)** (Kerner Lab, Arizona State
University) harmonises open field-boundary datasets into the fiboa GeoParquet
standard. Its India component is a conversion of the boundaries published with
Wang, Waldner & Lobell, *"Unlocking large-scale crop field delineation in
smallholder farming systems with transfer learning and weak supervision"*.

| Field | Value (verified 2026-09-01) |
|---|---|
| URL | `https://data.source.coop/kerner-lab/fields-of-the-world-india/boundaries_india_2016.parquet` |
| Size | 7,837,930 bytes — one file, direct HTTP, no registration |
| Licence | CC-BY-4.0 |
| Columns | `id`, `area`, `geometry`, `determination_datetime` |
| CRS | EPSG:4326 |
| Bounding box | 68.797°E – 96.237°E, 9.249°N – 34.533°N — **India's national extent** |
| Fields | ~10,000, manually delineated from Airbus SPOT high-resolution imagery |
| Vintage | 2016 |

**Why this changes the Model A position.** `boundary.evaluate_gate()` needs
held-out polygons to compute a median IoU against, and `MIN_GATE_SAMPLE = 100`.
Ten thousand Indian smallholder polygons is a hundred times that. The columns are
exactly what `agri.geometry` and `agri.registry` consume, and the areas mean
`area_mismatch()` can be exercised against real field sizes rather than squares.

**Why it is not the GPS-walk set, and LH-407 stays open.** These polygons are
**hand-delineated from imagery**, not walked. Phase 2 §8 forbids storing "any plot
polygon not observed or walked", and a photo-interpreted boundary is neither — it
is a careful human's reading of a picture, which is precisely the thing Model A
automates. So:

* it is a **valid Track P benchmark** for the delineation algorithm and its gate;
* it is **not admissible** as a bank plot boundary under §8, and
  `PlotSource.GPS_WALK` must not be used for it;
* the gate number it produces is a fact about a 2016 SPOT-derived benchmark, not
  about this bank's fields.

If it were adopted, `PlotSource` would need a fourth member — something like
`PHOTO_INTERPRETED` — sitting between `CADASTRAL` and `AUTO_DELINEATED` in
authority. That is a code change with a §8 question attached, so it is raised as
a ticket rather than made here.

---

## 3. Model B — crop labels: still blocked, and now measured

**[CropHarvest](https://github.com/nasaharvest/cropharvest)** is the dataset
Phase 2 §4 names. It is real and it is well built:

| Field | Value (verified 2026-09-01) |
|---|---|
| DOI | 10.5281/zenodo.7257688 |
| Licence | CC-BY-SA-4.0 |
| `labels.geojson` | 70,581,424 bytes — **downloaded and inspected** |
| `features.tar.gz` | 67.7 MB — pre-extracted pixel time series |
| `eo_data.tar.gz` | 21.7 GB — the full Earth Engine export |
| Total labels | 95,186, of which 33,205 have multiclass labels |

**And it cannot train an Indian crop classifier.** Counted directly from
`labels.geojson`:

```
points inside India's bounding box:        2,597
  of which from geowiki-landcover-2017:    2,497   (binary crop / non-crop only)
  of which from croplands:                   100
crop-typed points inside India:               34
  rice 15 · cotton 8 · maize 5 · groundnut 2 · millet 2 · cassava 1 · sunflower 1
```

Thirty-four labelled points, across seven crops, for a country with fifteen
agro-climatic zones. Phase 2 §7 asks for macro-F1 ≥ 0.85 **on the five majority
crops per zone**; there is not one zone here with five crops at double-digit
support.

This is worth stating precisely because CropHarvest is named in the phase file
and is easy to assume solves the problem. It does not, and the number that shows
it is 34.

**What would work instead**, in descending order of realism:

1. **Crop-cutting experiment (CCE) records.** India runs CCEs at scale under the
   General Crop Estimation Survey and, since 2016, under PMFBY at
   gram-panchayat granularity — geotagged, crop-tagged, yield-measured. This is
   the correct source and it is the one the phase file names first. It is not
   openly published as microdata; obtaining it is a `[POLICY]`/MoU question with
   the Ministry of Agriculture or the state agriculture department, not a
   download.
2. **Officer ground-truthing**, which §4 already mandates as a sampled subset of
   visits. This is the bank's own collection programme and is the same
   scheduling gap as LH-407.
3. **EuroCrops / EuroCropsML** for *method* development only — millions of
   parcels with crop types, but European crops, European calendars, European
   field sizes. Usable to prove the code path; a model trained on it says
   nothing about Kharif rice.

---

## 4. Model C — district yield statistics: available, portal-gated

**[ICRISAT District Level Database](http://data.icrisat.org/dld/)** (with Tata-Cornell
Institute) is the standard source for long-run Indian district agriculture.

| Field | Value |
|---|---|
| Coverage | 20 major crops — cereals, pulses, oilseeds, cotton, sugarcane, fruit and veg |
| Variables | Area, production, **yield** per district-crop-year |
| Period | 1966 to 2015-16 (apportioned to 1966 district boundaries for time-series continuity) |
| States | 19 |
| Access | Open, no fee |

**The practical catch, checked rather than assumed:** `data.icrisat.org/dld/` is a
form-driven portal. There is no stable direct-download URL — the crops page is a
`select2` form that builds a query. So unlike Fields of The World, which is one
`curl` away, this needs either interactive selection or a scripted form post, and
a `make trackp-p2` target could not fetch it unattended in the way `make trackp-p3`
fetches nothing (the Fannie Mae file is manually placed).

`fit_yield_model()` requires ≥ 30 district-seasons. ICRISAT supplies thousands.
The two covariates the fallback needs — peak NDVI and a rainfall percentile —
would come from §5.

**Alternatives**: [data.gov.in district-wise season-wise crop production
statistics](https://www.data.gov.in/catalog/district-wise-season-wise-crop-production-statistics-0)
(returned HTTP 500 when checked, so treat availability as intermittent), and the
[AIKosh District Crop Area Production Yield dataset](https://aikosh.indiaai.gov.in/home/datasets/details/district_crop_area_production_yield_dataset.html).

---

## 5. Weather, drought and terrain: fully available

None of these was ever the blocker, and all are open:

| Need | Source | Notes |
|---|---|---|
| Rainfall | [CHIRPS](https://www.chc.ucsb.edu/data/chirps) | 0.05° (~5 km), 1981–present, daily to annual |
| Reanalysis | [ERA5](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels) | Via the Copernicus Climate Data Store |
| Gridded India rainfall | IMD | The phase file's preferred source for India |
| **Pre-computed SPEI** | [Global high-resolution drought indices 1981–2022](https://essd.copernicus.org/articles/15/5449/2023/) and [ERA5-Drought](https://www.nature.com/articles/s41597-025-04896-y) | 5 km SPEI from CHIRPS + GLEAM PET |
| Soil | [SoilGrids](https://soilgrids.org) | Soil organic carbon for `LandQualityInputs` |
| Terrain | Copernicus DEM | Slope for `LandQualityInputs` |

**A note on the pre-computed SPEI grids.** They are a *validation opportunity*,
not a shortcut. `agri.drought` implements SPI and SPEI from the source papers and
the phase file mandates matching a published reference to two decimals. A 5 km
published SPEI grid for India is exactly such a reference, and comparing
`spei()` against it on real CHIRPS input would be a stronger test than the
property-based one currently in `tests/test_agri_drought.py`. That is a concrete,
unblocked piece of work.

**PET remains an input.** `spei()` takes PET rather than computing it, because
Penman-Monteith from raw reanalysis fields is a meteorological pipeline. GLEAM
or the ERA5-Drought product supplies it.

---

## 6. Mandi prices: the feed exists, LH-408 does not move

| Source | What it gives |
|---|---|
| [data.gov.in daily mandi prices](https://www.data.gov.in/catalog/current-daily-price-various-commodities-various-markets-mandi) | Min / max / **modal** price per commodity per market per day, JSON/CSV API. The public key is throttled to 10 commodities; registration lifts it |
| [CEDA Agri Market Data](https://agmarknet.ceda.ashoka.edu.in/) (Ashoka University) | The same Agmarknet data as a **historical** daily/monthly/yearly archive — which is what a P25 needs and the live API does not give |

**LH-408 is unchanged by this, and that is the point of the ticket.** The ticket
was never "where do we get prices" — §4 already names Agmarknet as `[DATA]`. It
is "P50 and P25 *of what distribution, over what window*": price at harvest,
across the marketing season, or a forward; at the nearest mandi or the one the
farmer actually sells at; over how many years. Having the full historical archive
makes every one of those computable and none of them decided. It is still a
`[POLICY]` call.

---

## 7. Imagery: ADR-0013 overstated this

ADR-0013 says a Phase 2 scene stack "is measured in terabytes". That is true of
raw L2A scenes and it is the wrong unit of analysis, because **nothing in
`agri/` consumes a scene.** `agri.ports.SceneSource` returns
`Observation(plot_id, acquired, value, valid)` — a per-plot reduction. Every
module downstream works on time series of numbers.

Three ways to get those without a raster archive:

1. **CropHarvest's `features.tar.gz` — 68 MB**, not 21.7 GB. It carries the
   Sentinel-1/2 + ERA5 + SRTM time series already extracted per point. The 21.7 GB
   `eo_data.tar.gz` is the raw export, and is optional.
2. **Sentinel Hub Statistical API / openEO** on the Copernicus Data Space, which
   returns per-polygon aggregated index series. You send geometry, you get a time
   series. This is the production shape of `SceneSource` on Track B and it moves
   kilobytes.
3. **Google Earth Engine `reduceRegions`**, the same pattern.

So the honest constraint is not storage. It is:

* **the crop calendar (LH-102)**, which decides the season windows every index is
  computed over — an unblocked pipeline still cannot say what "peak season" means
  without it; and
* **the plot polygons to reduce over**, which is LH-407 for the bank's own book —
  and Fields of The World now supplies a benchmark substitute (§2).

ADR-0013's conclusion (Track A only, no Track P) was right for Models B and C and
**wrong for Model A**. That correction is filed as a Phase 2 finding.

---

## 8. Agri loan outcomes: confirmed structurally blocked

This is LH-406, and it is the one that gates every exit criterion. The search
confirms there is nothing.

**What the RBI publishes**: agriculture GNPA as *aggregates* — by bank group, by
region, by state, in the Basic Statistical Returns, the Financial Stability
Report and the *Report on Trend and Progress of Banking in India*. Real numbers,
useful for context, and never loan-level.

**What exists in the literature**: single-institution datasets behind papers — a
Nicaraguan MFI's agri microloans, a Chinese CFPA Microfinance dataset, a Chinese
bank's ~4,500 agri enterprise loans with 64 defaults. All are proprietary,
obtained under research agreements, and none is Indian smallholder credit.

**What PMFBY offers**: crop *insurance* enrollment and claims, district-season
granularity, published as dashboards and mirrored on Kaggle. A claim is a
crop-loss event, not a credit event. It is a genuinely interesting **proxy
outcome** — a district-season claim ratio is a real measure of agricultural
distress and could support a *demonstration* of criterion (a)'s monotonicity
machinery. It is not agri NPA, and using it as one would be exactly the
substitution this repository exists to refuse.

**Therefore**: criteria (a), (b) and (c) stay **not measurable**. Criterion (b) in
particular cannot be approximated at all — it is a Gini uplift on *this bank's*
agri applications scored by *this bank's* P1 architecture, and no external data
constructs that.

---

## 9. What a bank collects instead — the Track B acquisition path

Everything above is Track P. This section is what the phase file assumes exists
on Track B and where it actually comes from inside a bank. It is written because
"the bank has the data" is doing a lot of work in Phase 2 §3, and the four items
have very different acquisition costs.

### 9.1 Plot polygons — the officer GPS walk (LH-407)

**The only §8-admissible source.** An officer opens the field app at the plot and
walks the perimeter; the app records a GPS track, closes the ring, and computes
area. What makes it work or fail:

* **Accuracy.** Consumer-phone GNSS is 3–5 m under open sky, worse under tree
  cover and near buildings. On a 1 ha field (100 m square) a 15 m systematic
  offset costs 43% of IoU — measured in `test_agri_geometry.py`. So the walk must
  record per-vertex accuracy and the app must reject a track whose dilution of
  precision exceeds a threshold, or the ground truth is noisier than the model.
* **Sampling, not census.** Walking every plot is impossible. The set must be
  *stratified* — by agro-zone, field size and crop — because Model A's error is
  correlated with exactly those, and a walk set drawn from convenient
  (large, near-road) plots produces a gate that passes and a model that fails on
  smallholdings.
* **Cost and lead time.** This is field labour across a season. It is the single
  most under-scheduled item in Phase 2 and the reason LH-407 is a **scheduling**
  ticket rather than a committee one.
* **Consent.** SRS §11.4: a plot polygon linked to a borrower is personal data.
  The walk needs a consent basis and the polygon needs the DPO's PII
  classification (LH-110).

### 9.2 Crop labels — crop-cutting experiments and sampled visits

Two channels, and the phase file names both:

* **CCE records.** India already runs crop-cutting experiments under the GCES and
  PMFBY at gram-panchayat level: a measured plot is harvested, weighed, and the
  crop and yield recorded with a location. This is ground truth for **Model B and
  Model C simultaneously** — the crop label and the yield — and it is the highest-value
  single dataset in the whole phase. A bank does not generate it; it obtains it
  under an MoU with the state agriculture department or the insurance
  implementing agency.
* **Officer photo + crop tag** on a sampled subset of visits, per §4. Cheap,
  because the officer is already at the plot, and it accumulates. The
  requirement that makes it usable is that the photo is geotagged and timestamped
  by the app rather than by the officer.

### 9.3 Yield — three sources, decreasing quality

1. CCE yields (above) — measured, plot-located, the gold standard.
2. State/district government statistics — what ICRISAT aggregates. Real,
   long-run, and **district-level**, which is why §4 downscales rather than
   predicting plot yield directly, and why `downscale()` returns the percentile
   that is the entire content of the plot claim.
3. Farmer-declared yields on the application — an input the bank already has and
   the least reliable, since it is self-reported by the party seeking credit.
   Useful as a cross-check against (1) and (2), never as a target.

### 9.4 Agri credit outcomes — already inside the bank

This is the one the bank does not need to acquire. LH-406 asks for the historical
agri portfolio with outcomes and location granularity, and every component exists
in the core banking system:

* **Loan master and repayment history** → the Appendix A default label, exactly
  as Phase 0's lakehouse contracts already define it;
* **Kisan Credit Card / crop loan account records**, which carry the crop and
  season the loan was sanctioned against — this is the raw material for LH-412's
  season attribution;
* **Location** at whatever granularity the LOS captured: plot GPS if the walk
  happened, else village, else pincode. Phase 2 §4's rule applies — village
  granularity is stored as village granularity and flagged.

**So LH-406 is not a data-collection problem; it is a data-access problem** — the
same LH-120 written-approval blocker as every other phase. The distinction is
worth keeping because it changes who unblocks it: not a survey team, but whoever
signs the data-sharing approval.

### 9.5 What a bank should start collecting now

If Phase 2 is on the roadmap, four things cost nothing to start and are
impossible to backfill:

1. **Geotag every agri site visit.** Not a new process — an added field on one
   that exists. Without it there is no ground truth in three years.
2. **Record the crop and season on the loan account**, not just in the appraisal
   note. This is LH-412's attribution rule made mechanical.
3. **Keep the sowing-verification date** when disbursal is tranched against it —
   this is criterion (c)'s flag date, and it cannot be reconstructed later.
4. **Snapshot the plot polygon at decision time**, not just currently. Every
   feature in this phase is point-in-time, and a registry that only holds the
   *current* boundary makes the backtest in §7 impossible on its own history.

---

## 10. Tickets this document affects

| Ticket | Effect |
|---|---|
| **LH-407** | Unchanged as the bank's GPS-walk requirement. **Narrowed**: Model A's *benchmark* no longer needs it (§2), only its production ground truth does |
| **LH-404** | Unchanged. A ratified zone crop list is a policy artifact; no dataset supplies it |
| **LH-406** | Unchanged and reconfirmed (§8). Reclassified as a data-*access* problem under LH-120 rather than a collection problem (§9.4) |
| **LH-408** | Unchanged (§6). The archive exists; the window is still undecided |
| **LH-102** | Unchanged, and now the **binding** constraint on the imagery pipeline (§7) |
| **New** | `PlotSource` needs a `PHOTO_INTERPRETED` member if Fields of The World is adopted — a §8 question, raised as a finding |
