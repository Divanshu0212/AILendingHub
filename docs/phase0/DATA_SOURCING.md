# Data inventory — what is synthetic, and what real data replaces it

Every byte of data in this repository is synthetic and confined to
`tests/fixtures/`, per Master §2 rule 3. Nothing here has been near a bank.

This document exists so that swapping in real data is a mechanical task rather
than an archaeology project. It has three parts: **what is fake right now**,
**what real data replaces each piece**, and **exactly how to plug it in**.

---

## 1. Everything synthetic in this repository

| # | Where | What it is | Rows | What it stands in for |
|---|---|---|---|---|
| 1 | [tests/fixtures/identity/cbs_loans.csv](../../tests/fixtures/identity/cbs_loans.csv) | Loans with deliberate key defects | 9 | CBS active-loan extract |
| 2 | [tests/fixtures/identity/los_applications.csv](../../tests/fixtures/identity/los_applications.csv) | Applications incl. one declined | 6 | LOS application extract |
| 3 | [tests/fixtures/identity/collections_cases.csv](../../tests/fixtures/identity/collections_cases.csv) | Cases incl. one orphan | 3 | Collections case extract |
| 4 | `lending_hub.serving.loadtest._fixture_harness` | Generated tokens + one feature | 2000 | Serving load-test traffic |
| 5 | `lending_hub.serving.parity._track_a_harness` | Generated sample scored two ways | 1000 | The frozen 12-month WS-0.4 sample |
| 6 | `lending_hub.mlops.reproducibility_test._dataset` | Seeded two-feature classification set | 400 | A tagged lakehouse training snapshot |
| 7 | In-test literals across `tests/` | Small hand-written cases | — | Nothing; they test logic, not data |

**These are not a miniature portfolio.** The identity fixtures in particular are
built to fail: they carry one instance of every root cause the join audit can
emit, so a regression that stops detecting one breaks a test instead of quietly
reporting a better join rate. Do not read the 83% join rate they produce as a
data-quality estimate — it is a property of the fixtures.

Items 4–6 are generated at runtime and never written to disk. Item 6 is a toy
logistic regression that exists only to prove the reproducibility triplet
determines the model; **it is not a credit model and must never become one.**

Nothing above may be copied into a Silver table, a training table, or a report.
`FixtureReader` enforces this at runtime — it refuses any path outside
`tests/fixtures/` — and grounding rule G5 enforces it in CI.

---

## 2. What real data replaces each piece

### 2.1 Bank sources — blocked on written approval (LH-120)

These need the data-sharing approvals Phase 0 §3 lists as *entry* criteria. Each
row names the registry entry that already specifies the contract.

| Source | Registry file | What to request | History |
|---|---|---|---|
| **Core banking** | [config/sources/cbs.yaml](../../config/sources/cbs.yaml) | Applications, disbursals, month-end account snapshots, DPD histories, write-offs, recoveries | ≥ 5 years (7+ if available) |
| **Loan origination** | [config/sources/los.yaml](../../config/sources/los.yaml) | Applications, decisions, underwriter overrides — **including declined applications** | ≥ 5 years |
| **Collections** | [config/sources/collections.yaml](../../config/sources/collections.yaml) | Actions, promise-to-pay outcomes, recoveries, restructures | ≥ 5 years |
| **Bureau** | [config/sources/bureau.yaml](../../config/sources/bureau.yaml) | **Archived as-of-decision responses**, not fresh pulls | Matching the application history |
| **Account Aggregator** | [config/sources/account_aggregator.yaml](../../config/sources/account_aggregator.yaml) | Consent-bound statement data + the consent artifacts | Per consent |
| **KYC / documents / devices** | [config/sources/kyc_documents_devices.yaml](../../config/sources/kyc_documents_devices.yaml) | KYC records, document forensics artifacts, device telemetry | Per DPO classification |
| **Event streams** | [config/sources/repayment_events.yaml](../../config/sources/repayment_events.yaml) | Repayment postings + application submissions on Kafka | Live |
| **Finance GL** | — (LH-150) | Product/balance-type → GL account mapping, plus period-end GL balances | Reconciliation periods |

Three requests are easy to get wrong and expensive to redo:

1. **Declined applications from LOS.** A training set built only on booked loans
   carries the reject-inference gap into every P1 model. Ask for declines in the
   first extract, not the second.
2. **Archived bureau responses, not re-pulls.** Re-pulling a bureau report today
   to build a 2023 training row injects information that did not exist at the
   decision point. If only re-pulls are available, say so loudly — it changes
   what P1 can claim.
3. **`created_timestamp`, not just `event_timestamp`.** Every extract needs the
   time the *platform learned* each fact, not only when it was true. Without it
   no point-in-time join is correct, and this is usually the field an extract
   team drops because it "looks redundant". See
   [featurestore/pit.py](../../src/lending_hub/featurestore/pit.py).

### 2.2 Public sources — obtainable today, no approval needed

Nothing blocks these. They are P2 inputs, registered in Phase 0 so the ingest
contract and licensing are settled before P2 starts.

| Source | Where to get it | Notes |
|---|---|---|
| **Sentinel-1/2** | Copernicus Data Space Ecosystem (`dataspace.copernicus.eu`) — free account, API + browser | Sentinel-2 optical, Sentinel-1 SAR for cloud-penetrating observation |
| **Landsat** | USGS EarthExplorer (`earthexplorer.usgs.gov`) — free account | Longer historical archive than Sentinel |
| **ERA5 reanalysis** | Copernicus Climate Data Store (`cds.climate.copernicus.eu`) — free account, `cdsapi` client | Keep the product **vintage** per grid-cell-day; reanalysis is revised after publication and a point-in-time join will otherwise pick up a value that did not exist yet |
| **CHIRPS rainfall** | UCSB Climate Hazards Center (`chc.ucsb.edu/data/chirps`) — direct download, no account | |
| **IMD** | India Meteorological Department (`imdpune.gov.in`) — gridded datasets | Licensing varies by product |
| **SoilGrids** | ISRIC (`soilgrids.org`) — open licence, WCS/REST | |
| **Cadastral parcels** | State-by-state land-records portals | Not uniformly open; licensing is a Legal question per state, unlike SoilGrids |

If you want to exercise the geospatial path before bank data arrives, these are
the ones to start with — they are real data, so they are not synthetic under
Master §2 rule 3, and they can populate a genuine Bronze layer today.

### 2.3 If you do not have a bank at all

Two honest options, and one anti-pattern:

- **Public loan-performance data.** Anything with an application date, an outcome,
  and a genuine time dimension can exercise the whole platform path honestly —
  provided you record it as what it is. Register it as a source in
  `config/sources/`, set `kind: public`, and it flows through the same code.
- **Bank-shaped data from a real institution under an agreement.** The path this
  repo is built for.
- **Anti-pattern: generating a "realistic" synthetic portfolio and treating its
  numbers as results.** The code will run and every gate will produce a number.
  Those numbers would describe the generator, not a portfolio — and once they are
  in a report, nobody downstream can tell the difference. If synthetic data is
  used to demo the pipeline, every number it produces must stay stamped Track A.

---

## 3. Plugging real data in

Track A readers take CSV. The columns below are what
[`SPINE_KEY_COLUMNS`](../../src/lending_hub/identity/ports.py) expects.

**CBS loans** — one row per loan:

```csv
loan_id,customer_id,account_id,is_active,disbursed_on
LN-1001,CU-5001,AC-7001,true,2025-02-11
```

**LOS applications** — one row per application, **including declines**:

```csv
application_id,loan_id,customer_id,decision,decided_at
AP-3001,LN-1001,CU-5001,approved,2025-02-09
```

**Collections cases** — one row per case:

```csv
case_id,loan_id,customer_id,opened_on,status
CS-9002,LN-1002,CU-5002,2025-06-14,open
```

Then:

```bash
# 1. Put the extracts anywhere OUTSIDE tests/fixtures/ — they are real data now.
mkdir -p data/bronze   # already gitignored

# 2. Point the audit at them.
python -m lending_hub.identity.audit --fixtures data/bronze --enforce-gate
```

`FixtureReader` will refuse: it only reads `tests/fixtures/`, by design. Real data
needs a reader without that guard — implement `LakehouseReader.records()` in
[identity/ports.py](../../src/lending_hub/identity/ports.py) against wherever the
extracts land. That refusal is the boundary working correctly, not an obstacle:
it means synthetic and real data cannot be read by the same code path by accident.

Once real extracts exist, the reports become **Track B** and, for the first time,
count as Phase 0 gate evidence (ADR-0003).

### What each real dataset immediately unblocks

| You provide | This starts working |
|---|---|
| CBS + LOS + collections extracts | Join-rate audit → the WS-0.1.3 gate (≥ 99.5%) |
| GL balances + product mapping (LH-150) | Reconciliation → the WS-0.1.5 gate (≤ 0.1%) |
| A live Kafka topic | Freshness dashboard → the WS-0.1.4 gate (< 60 s) |
| Legacy scorecard outputs on a frozen sample | Parity harness → the WS-0.4 gate (≥ 99.9%) |
| Any of the above with timestamps | Point-in-time joins on real ingestion lag, which is where leakage actually lives |
