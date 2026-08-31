# Phase 2 — Agri Intelligence: Satellite, Weather, Crop & Geo

| Phase card | |
|---|---|
| Duration | Months 4–8 — **must overlap one full crop season** |
| SRS modules | §3 (agricultural lending intelligence) |
| Depends on | Phase 0 gate passed (runs parallel to Phase 1) |
| Unblocks | Agri-segment scoring (with P1 architecture), P4 agri EWS triggers, P7-dashboard weather overlays |
| Squads | Geospatial DS (R), Agri credit business (C/owner of policy inputs), Platform (C), Model Risk (A) |
| Governing contract | `00_MASTER_Implementation_Guide.md` §2–§4 — binding |

**Objective.** Build the satellite/weather pipeline and its three models (boundary delineation, crop classification, yield estimation), aggregate them into deterministic credit features (`ExpectedIncome`, `StressedIncome`, `LandQualityIndex`), and **prove on historical seasons** that these features order agri risk — shipping first as underwriter-visible evidence, then as scoring features. The models inform; they never autonomously decide.

---

## 2. Position in the program

**Inputs from P0:** lakehouse, Feast, identity spine, MLflow/CI. **From the business:** ratified agro-zone crop calendars, input-cost tables, sowing windows `[POLICY: Agri Credit Head]`.

**Outputs to later phases:**

| Output | Consumed by |
|---|---|
| Plot registry (PostGIS) + per-plot feature time series in Feast | Agri scoring, P4 EWS, dashboards |
| `ExpectedIncome`, `StressedIncome`, `LandQualityIndex`, climate-risk features | Agri-segment scoring (P1 architecture), P4 affordability caps |
| Sowing/crop verification stream per revisit | P4 EWS agri triggers; disbursal tranching |
| District SPEI/NDVI anomaly layers | P3 dashboards, P3 macro conditioning |
| Underwriter map/evidence UI | Agri underwriting workflow |

---

## 3. Entry criteria

- P0 gate passed.
- `[DATA]` inventory of historical agri portfolio with outcomes and location granularity (plot GPS / village / pincode) completed.
- `[POLICY: Agri Credit Head]` ratified: agro-climatic zones, per-zone crop lists, sowing windows, input costs per crop. **These are policy inputs — a model or an AI assistant must never guess a crop calendar.**

---

## 4. Workstreams

### WS-2.1 Data pipelines (build these before any model)

1. **Imagery ingestion.** Copernicus Data Space API: Sentinel-2 L2A (optical, 10 m, ~5-day) + Sentinel-1 GRD (SAR, cloud-proof) over operating districts. Weather: [CHIRPS](https://www.chc.ucsb.edu/data/chirps) rainfall + [ERA5](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels) reanalysis + IMD gridded. Statics: [SoilGrids](https://soilgrids.org), Copernicus DEM. All rasters stored as cloud-optimized GeoTIFF; per-source ingestion DAGs with missing-tile completeness monitors.
2. **Plot registry (PostGIS).** Row = {polygon, source ∈ (GPS-walk, cadastral, auto-delineated), confidence, loan link via identity spine}. Where no polygon exists: **never geocode a village centroid and store it as a plot** — village-granularity features are stored at village level and flagged as such. Officer mobile app captures GPS walk-around tracks as the ground-truth channel.
3. **Index computation.** Per plot: NDVI/EVI time series (cloud-masked via Sentinel-2 scene-classification layer), Sentinel-1 VV/VH backscatter series. Per district/plot: SPI ([McKee et al., 1993](https://climate.colostate.edu/pdfs/relationshipofdroughtfrequency.pdf)) and SPEI ([Vicente-Serrano et al., 2010](https://journals.ametsoc.org/view/journals/clim/23/7/2009jcli2909.1.xml); reference implementation [spei](https://spei.csic.es/)). **Unit test:** recompute SPI on a published station example, match to 2 decimals — reference-implementation rule (Master §2.2).

### WS-2.2 Models, in dependency order

**Model A — Boundary delineation** (SRS §3.4.1).
Fine-tune **SAM** ([Kirillov et al., arXiv:2304.02643](https://arxiv.org/abs/2304.02643)) or U-Net ([arXiv:1505.04597](https://arxiv.org/abs/1505.04597)) on peak-season temporal max-NDVI composites + officer GPS-walk labels; post-process: watershed + polygonize (GDAL); snap to digitized cadastral layers where available; >20% claimed-vs-observed area mismatch → underwriter flag (fraud signal). **Gate:** median IoU vs. held-out GPS-walk polygons ≥ 0.75 before auto-delineations are shown; below it, plots require a manual walk.

**Model B — Crop classification** (SRS §3.4.2).
Fine-tune **Presto** ([Tseng et al., arXiv:2304.14065](https://arxiv.org/abs/2304.14065), [repo](https://github.com/nasaharvest/presto)) per agro-zone. Labels: crop-cutting experiment sites, officer ground-truthing (mandatory photo + crop tag on a sampled subset of visits), [CropHarvest](https://github.com/nasaharvest/cropharvest) where geographically valid. Class set = ratified zone crop list **+ fallow** (first-class label). Baseline: Random Forest on NDVI time-series statistics — **Presto ships only if ≥ +5 macro-F1 points over the baseline** (complexity must be earned). Calibrate per-class probabilities (temperature scaling); predictions < 0.6 confidence surface as "unsure", never forced.

**Model C — Yield estimation** (SRS §3.4.3).
Reference method: histogram-CNN/LSTM + Gaussian Process — [You, Li, Low, Lobell & Ermon, AAAI 2017](https://cs.stanford.edu/~ermon/papers/cropyield_AAAI17.pdf) ([code](https://github.com/JiaxuanYou/crop_yield_prediction)); transfer-learning variant for data-scarce zones ([Wang et al., COMPASS 2018](https://dl.acm.org/doi/10.1145/3209811.3212707)). Train district-level on government yield statistics; downscale to plot via relative NDVI position in the district distribution. **Build the auditable fallback first**: regression on peak NDVI + rainfall percentile — kept forever as sanity check and imagery-outage fallback. Output contract: P50 / P25 / P10 yield (the GP uncertainty is part of the contract, not optional).

### WS-2.3 Aggregation to credit features (deterministic, policy-owned)

```
ExpectedIncome  = Σ plots,seasons  Area × Yield_P50 × Price_P50 − InputCosts
StressedIncome  = Σ plots,seasons  Area × Yield_P25 × Price_P25 − InputCosts
LandQualityIndex = f(soil organic carbon, slope, irrigation proxy,
                     5-yr mean peak-NDVI percentile vs agro-zone,
                     yield volatility, drought frequency)
```

Implemented as SQL/Python owned by Credit Policy; formula changes need `[POLICY]` sign-off. Input costs `[POLICY: Agri Credit Head]`; mandi price distributions from Agmarknet feeds `[DATA]`. Climate features: drought frequency (share of last 20 seasons with SPEI ≤ −1), excess-rain frequency, heat-stress days in crop-critical windows, irrigation proxy.

### WS-2.4 Backtest before any live use

On ≥ 3 historical seasons, computing everything as-of historical decision dates (point-in-time imagery only):

- **(a)** LandQualityIndex quartiles order historical agri NPA rates **monotonically**;
- **(b)** adding agri features to the P1 model architecture on the agri portfolio yields **≥ +4 Gini** `[SPEC]`;
- **(c)** the non-sowing flag would have fired on **≥ 60%** of season-linked defaults with **≥ 45 days** lead.

A failed test triggers feature redesign — never threshold relaxation.

---

## 5. Shipping ladder

1. **Underwriter evidence UI first** — map with plot polygons, NDVI time-slider, drought history, crop verification status. Humans use it while models season; override notes are captured as labels.
2. **Scoring shadow** — agri-segment model (P1 architecture + agri features) shadows for one season-quarter.
3. **Live for new agri originations** — including the two-season sowing-verification rule for disbursal tranching `[POLICY: Agri Credit Head]`.
4. **Monitoring loop** — every satellite revisit updates plot status; non-sowing/distress events flow to the weekly agri-risk report now, and to the P4 EWS once it ships.

## 6. Deliverables checklist

- [ ] Ingestion DAGs (S2/S1/CHIRPS/ERA5/IMD/SoilGrids/DEM) + completeness monitors
- [ ] Plot registry (PostGIS) + officer GPS-walk capture in the field app
- [ ] Index pipelines with SPI unit test green
- [ ] Model A/B/C registered in MLflow with model cards
- [ ] RF baseline + fallback yield regression (kept, documented)
- [ ] Feature aggregation package with policy sign-off record
- [ ] Backtest report (a)/(b)/(c) with scripts
- [ ] Underwriter evidence UI live; adoption telemetry
- [ ] Geographic disparate-impact analysis of agri features (SRS §11.3)

## 7. Exit criteria (gate review)

Backtests (a)–(c) pass · crop classifier macro-F1 ≥ 0.85 on the 5 majority crops per zone on held-out ground truth · boundary IoU gate met · underwriter adoption ≥ 70% of agri files opened in the evidence UI · model cards + independent validation for Models A/B/C · disparate-impact memo filed.

## 8. Do-not-invent list (P2)

Crop calendars & sowing windows · per-crop input costs · disbursal-tranching rules · qualifying-crop lists · natural-calamity relief treatment (RBI norms apply) · any plot polygon not observed or walked. All `[POLICY]` or `[DATA]`.

## 9. References for this phase

- You et al. — *Deep Gaussian Process for Crop Yield Prediction*, AAAI 2017 — [PDF](https://cs.stanford.edu/~ermon/papers/cropyield_AAAI17.pdf) · [code](https://github.com/JiaxuanYou/crop_yield_prediction)
- Wang et al. — transfer learning for yield, COMPASS 2018 — [DOI](https://dl.acm.org/doi/10.1145/3209811.3212707)
- Tseng et al. — *Presto* — [arXiv:2304.14065](https://arxiv.org/abs/2304.14065) · [CropHarvest](https://github.com/nasaharvest/cropharvest)
- Rußwurm & Körner — satellite time-series classification — [arXiv:1901.10681](https://arxiv.org/abs/1901.10681)
- Kirillov et al. — *Segment Anything* — [arXiv:2304.02643](https://arxiv.org/abs/2304.02643); Ronneberger et al. — *U-Net* — [arXiv:1505.04597](https://arxiv.org/abs/1505.04597)
- Vicente-Serrano et al. — *SPEI* — [link](https://journals.ametsoc.org/view/journals/clim/23/7/2009jcli2909.1.xml); McKee et al. — *SPI* — [PDF](https://climate.colostate.edu/pdfs/relationshipofdroughtfrequency.pdf)
- Satellite credit evidence — [Ann. Oper. Res. 2026](https://link.springer.com/article/10.1007/s10479-024-06299-5) · [IJFS 2026](https://www.mdpi.com/2227-7072/14/7/187) · [WEF 2023](https://www.weforum.org/stories/2023/07/how-geospatial-datasets-improve-lending-to-india-farmers/)
- Data: [Sentinel-2](https://sentinels.copernicus.eu/web/sentinel/missions/sentinel-2) · [CHIRPS](https://www.chc.ucsb.edu/data/chirps) · [ERA5](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels) · [SoilGrids](https://soilgrids.org)
