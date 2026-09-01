# Data inventory — what is synthetic, and what real data replaces it

Three kinds of data now exist in this repository, and the distinction is
load-bearing (ADR-0003, [ADR-0004](../adr/0004-public-reference-data-track.md)):

| Track | What | Where | Gate evidence |
|---|---|---|---|
| **A** | Synthetic fixtures | `tests/fixtures/` | No |
| **P** | Real public reference data | `datasets/` (gitignored) | **No** |
| **B** | This bank's own data | — none yet | **Yes** |

This document covers all three: what is synthetic, what real data has arrived and
how far it goes, and what is still missing.

## 0. Status of the datasets supplied (2026-09-01)

| Dataset | Verdict |
|---|---|
| **Fannie Mae** 2007Q1 + 2019Q1 | **In use.** Adapter built, 28.5M rows profiled, Appendix A labels produced |
| **Home Credit** | **In use for Phase 1.** Four files missing, including the one that mattered |
| **PKDD'99** | **Not usable as supplied.** See below — this one needs a decision |

### Fannie Mae — working

Both vintages parse and profile. Adapter: `lending_hub.sources.fanniemae`.

```bash
python -m lending_hub.sources.profile --path "datasets/Fannie Mae/2019Q1.csv" \
    --vintage 2019Q1 --out reports/trackP_fanniemae_2019Q1.json
```

Format note: despite the `.csv` extension the export is **pipe-delimited, no
header, 113 fields**, one row per loan per reporting month. The column map was
derived by profiling value distributions rather than transcribed from a
remembered layout, and `verify_layout()` re-checks it against every file before
any number is trusted — an index one position out reads a plausible wrong column
and every downstream figure would be confidently wrong with nothing to notice.

The delinquency status maps onto Appendix A with no tuning at all: Fannie reports
*months* delinquent in 30-day steps, so status `03` lands exactly on the default
threshold and `01`-`02` land exactly inside the indeterminate band. That
alignment is the reason this dataset is worth 8 GB of disk.

### Home Credit — partially usable

Present: `application_train`, `application_test`, `bureau`, `POS_CASH_balance`
(which carries a real `SK_DPD`, up to 2,672 days).

**All three usable files are now in use.** Phase 1 aggregates `bureau.csv`
(1,716,428 records) and `POS_CASH_balance.csv` (10,001,358 monthly balances) per
applicant — adapter `lending_hub.sources.homecredit_history`. Between them they
supply the bureau group the WS-1.1 Step 2 catalogue leads with (enquiries,
utilisation, DPD history, file age) and prior repayment behaviour, and five bureau
features land in the top ten by information value. Running without them cost the
challenger about 4 Gini points and nearly half its Brier skill.

Missing: `previous_application.csv`, `installments_payments.csv`,
`bureau_balance.csv`, `credit_card_balance.csv`.

`previous_application.csv` is the one that mattered. It carries the
Approved/Refused/Canceled statuses — the declined applications that make reject
inference exercisable, which was the whole reason to prefer this dataset for the
LOS role. Without it, Home Credit cannot stand in for LOS. Worth re-downloading
if you still have the Kaggle page open.

**What Phase 1 does with it anyway.** `application_train.csv` alone is enough for
the WS-1.1 scorecard: 307,511 unsecured consumer applications, an 8.0% bad rate,
and — uniquely among the three datasets — gender, age and region, without which a
fairness harness has nothing to run on. [ADR-0010](../adr/0010-scored-product-and-track-p-standin.md)
records why Phase 1 uses this source for the scorecard and Fannie Mae for the
out-of-time vintage discipline, rather than forcing one dataset to do both.

Two limitations follow the data everywhere it goes, and both are stamped into the
output rather than left in this document:

- **`TARGET` is not Appendix A.** It is the publisher's own payment-difficulty
  flag, with the publisher's window and thresholds, and the DPD history that would
  let Appendix A be applied instead is not published. Every target table built from
  it is `LabelProvenance.VENDOR` and reports `appendix_a_aligned: false`.
- **Reject inference is not exercisable.** No declined applications exist here, so
  the run ships a reject-inference *memo* stating the selection-bias limitation —
  which is precisely what Phase 1 §4 Step 8 asks for when the correction cannot be
  made.

Adapter: `lending_hub.sources.homecredit`. Run with `make trackp-p1`.

### PKDD'99 — not usable, and worth understanding why

Only two files arrived, `order_b.csv` and `trans_b.csv`, and neither is a raw
PKDD table. Both are **pre-aggregated feature tables** with columns like
`alltime_sum_trans_amount_by_account_id`, `1yr_mean_trans_amount_by_account_id`
and `trans_ratio_98_97`. The eight raw tables (`account`, `client`, `loan`,
`disp`, `card`, `district`, and the real `trans`/`order`) are absent.

Two problems, and the second is the serious one:

1. **No raw rows, no dates.** Without per-transaction timestamps there is nothing
   to replay as a stream and no identity spine to build — the tables it would
   join are not here.
2. **The aggregates are leakage by construction.** `alltime_sum_...` is computed
   over each account's entire history with no observation point. Joined to an
   application, it carries information from *after* the decision. That is exactly
   the defect finding B1 exists to prevent, and the platform's own point-in-time
   join would have no way to detect it, because the leakage is baked into the
   column before the join ever runs.

So these files cannot be used as features under Master §2 without a written
exception. If you want PKDD in the mix, the raw dataset is at
https://sorry.vse.cz/~berka/challenge/pkdd1999/ — the `data_berka` archive with
all eight tables. Otherwise Fannie Mae already covers what PKDD would have.

---

## 1. What is synthetic, and what real data replaces it

---

### 1.1 Everything synthetic in this repository

| # | Where | What it is | Rows | What it stands in for |
|---|---|---|---|---|
| 1 | [tests/fixtures/identity/cbs_loans.csv](../../tests/fixtures/identity/cbs_loans.csv) | Loans with deliberate key defects | 9 | CBS active-loan extract |
| 2 | [tests/fixtures/identity/los_applications.csv](../../tests/fixtures/identity/los_applications.csv) | Applications incl. one declined | 6 | LOS application extract |
| 3 | [tests/fixtures/identity/collections_cases.csv](../../tests/fixtures/identity/collections_cases.csv) | Cases incl. one orphan | 3 | Collections case extract |
| 4 | `lending_hub.serving.loadtest._fixture_harness` | Generated tokens + one feature | 2000 | Serving load-test traffic |
| 5 | `lending_hub.serving.parity._track_a_harness` | Generated sample scored two ways | 1000 | The frozen 12-month WS-0.4 sample |
| 6 | `lending_hub.mlops.reproducibility_test._dataset` | Seeded two-feature classification set | 400 | A tagged lakehouse training snapshot |
| 7 | [tests/fixtures/fanniemae/](../../tests/fixtures/fanniemae/) | Six loans in Fannie's 113-field format | 62 | One per Appendix A label path the adapter must get right |
| 8 | In-test literals across `tests/` | Small hand-written cases | — | Nothing; they test logic, not data |

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

### 2.3 Recommended public datasets — download these

No bank attached, so these are the stand-ins that let the platform run on **real
data with real time dimensions**. Real data is not synthetic under Master §2
rule 3, so it can populate a genuine Bronze layer — but it is not *this bank's*
data, so anything computed from it is still labelled for what it is.

Start with the first two. All links are the official sources; several need a free
account.

#### Tier 1 — start here

| Dataset | Link | Size | Stands in for |
|---|---|---|---|
| **PKDD'99 Financial (Berka)** | https://sorry.vse.cz/~berka/challenge/pkdd1999/ | ~15 MB | CBS + LOS + a transaction stream |
| **Home Credit Default Risk** | https://www.kaggle.com/competitions/home-credit-default-risk/data | ~700 MB | LOS + bureau + collections |

**PKDD'99** is real Czech bank data with eight related tables — `account`,
`client`, `disp`, `loan`, `trans`, `order`, `card`, `district` — and genuine
absolute dates. It is tiny, which is the point: it is the fastest way to wire the
identity spine end to end against something that actually has referential
integrity problems. `trans` (1M rows) can be replayed as the repayment stream.

**Home Credit** maps onto the origination side unusually well:

| File | Maps to |
|---|---|
| `application_train.csv` | LOS applications + target |
| `previous_application.csv` | **Prior applications with `NAME_CONTRACT_STATUS` ∈ Approved / Refused / Canceled** — real declines, so reject inference is exercisable |
| `bureau.csv`, `bureau_balance.csv` | Bureau source, with monthly balances |
| `installments_payments.csv` | Repayment postings |
| `POS_CASH_balance.csv`, `credit_card_balance.csv` | Monthly account snapshots |

Its one real weakness: timestamps are **relative day offsets** (`DAYS_DECISION`,
`DAYS_BIRTH` as negative integers), not absolute dates. Good for structure and
joins, weak for genuine point-in-time work — which is why Tier 2 matters.

#### Tier 2 — for real point-in-time work

| Dataset | Link | Size | Stands in for |
|---|---|---|---|
| **Freddie Mac Single-Family Loan-Level** | https://www.freddiemac.com/research/datasets/sf-loan-level-dataset | GBs (per-year files) | CBS monthly snapshots + DPD + dispositions |
| **Fannie Mae Single-Family Loan Performance** | https://capitalmarkets.fanniemae.com/credit-risk-transfer/single-family-credit-risk-transfer/fannie-mae-single-family-loan-performance-data | GBs (per-quarter files) | Same |

Both need a free registration. Take **one or two years first**, not the full
history — the whole archive is tens of GB and nothing here needs it.

These are the best available fit for the platform's hardest requirement. Each has
an *origination* file plus a *monthly performance* file carrying a reporting
period, a current delinquency status, and a zero-balance code (prepayment, short
sale, REO — the write-off analogues). That gives you:

- Genuine **month-end snapshots** → Appendix A's DPD cadence and the behavioural
  observation point, not a simulation of them.
- A real **12-month outcome window** with real defaults.
- And the one thing no other public dataset offers: because each monthly file is
  *published* on a known later date, the file's publication period is a
  legitimate `created_timestamp`. That makes finding **B1** — the two-timestamp
  point-in-time join — exercisable against real ingestion lag rather than against
  a fixture. It is the single most valuable thing you can download for this
  project.

#### Tier 3 — P2 geospatial, no approval needed

| Source | Link | Account |
|---|---|---|
| Sentinel-1/2 | https://dataspace.copernicus.eu | free |
| Landsat | https://earthexplorer.usgs.gov | free |
| ERA5 reanalysis | https://cds.climate.copernicus.eu | free (`cdsapi` client) |
| CHIRPS rainfall | https://www.chc.ucsb.edu/data/chirps | none |
| SoilGrids | https://soilgrids.org | none |
| IMD gridded data | https://www.imdpune.gov.in | varies |
| India open data (crop, rainfall) | https://data.gov.in | free |

Not needed for Phase 0. Download when P2 starts.

#### What these still will not unblock

Be clear-eyed about this:

| Gate | Status with public data |
|---|---|
| Join rate (WS-0.1.3) | **Exercisable** — PKDD'99 and Home Credit both have multi-table joins with genuine key defects |
| Stream freshness (WS-0.1.4) | **Exercisable** — replay PKDD'99 `trans` or Home Credit `installments_payments` through Kafka |
| Point-in-time correctness (WS-0.2.1) | **Exercisable** with Freddie/Fannie monthly publication dates |
| GL reconciliation (WS-0.1.5) | **Still blocked.** No public dataset ships an independent general ledger, and reconciling a dataset against an aggregate derived from itself proves nothing |
| Scorecard parity (WS-0.4) | **Still blocked.** There is no legacy scorecard to rebuild. The Track A batch-vs-serving comparator remains the substitute |

Two of the four numeric gates stay blocked on a real bank. That is not a gap in
the download list — it is what those two gates are *for*.

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
