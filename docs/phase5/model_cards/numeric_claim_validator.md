# Model Card — Uncited-numeric-claim validator (SRS §8.3.1)

> **This card documents something that is not a model, and that is deliberate.**
> Master §2 rule 5 requires a card for anything whose behaviour decides what
> reaches a customer, and this component decides whether a number the assistant
> produced is shown or stripped. It is a parser, its behaviour is exhaustively
> specified, and it has no parameters — which makes it the *easiest* component in
> Phase 5 to review and the one whose review matters most, because Phase 5 §7
> makes its output a hard gate.

## 1. Identification

| Field | Value |
|---|---|
| Name / version | `assistant.answer.validate` v0.1.0 |
| Components | `find_numeric_claims`, `split_sentences`, `parse_sentence`, `ValidatedAnswer` |
| Reference | Phase 5 §4 WS-5.3 step 1 — *"a post-generation validator … drops any uncited numeric claim. This validator is deterministic code, not another LLM."* |
| Registry stage | None — not a registered model |
| Model tier | Tier 1 by consequence: it is the last control before a number reaches a customer |
| Owner (accountable) | GenAI squad lead |
| Independent validator | **Not assigned.** Master §3.1 requires a validator who is not the developer; none exists |

## 2. Reproducibility

| Field | Value |
|---|---|
| Determinism | Total. Same input string, same resolver set, same output — no seed, no state, no model call |
| Config | None. There are no thresholds, no tuning parameters and no scores |
| Auditability | A verdict eight years old can be re-derived from the stored answer text and the stored citation set (Master §3.3) |

The absence of configuration is the property worth noting at a gate review. Every
other control in this programme has a threshold somebody chose; this one has a
grammar, and a grammar can be read.

## 3. Purpose and scope

Parses a generated answer sentence by sentence and drops any sentence that makes
a numeric claim without a resolvable citation or an allow-listed tool marker. If
nothing survives, the answer becomes a handoff.

**It decides citation, not truth.** Whether the cited passage *supports* the
number is entailment, is not decidable by parsing, and belongs to
`assistant.faithfulness`. An answer can pass this validator perfectly and be
unfaithful — every sentence cited, every citation resolving, and the passage
saying something else.

**It must not be used for**: verifying that an answer is correct; replacing the
faithfulness scorer; or as evidence that a deployed assistant does not leak
uncited numbers, unless that deployment routes every answer through
`validate()`.

## 4. The guarantee, and its exact boundary

`ValidatedAnswer.__post_init__` raises if any *kept* sentence carries a numeric
claim with no resolvable citation. The invariant is on the type, not inside
`validate()`, so a future code path that assembles an answer another way cannot
escape it — and "another way" is what a refactor is.

That makes Phase 5 §7's **uncited-numeric leak rate = 0** a property rather than
a measurement. The criterion asks for it to be established by weekly audit; an
audit samples, and a sample can show a rate is low but never that it is zero.

Two boundaries, both narrower than the guarantee sounds:

1. **It guards a code path.** A generation service that renders model output
   without calling `validate()` is outside it entirely. The function returns a
   new object rather than mutating a string, so skipping it leaves the caller
   with nothing to render — which is the strongest structural nudge available
   without owning the service.
2. **It is about citation, not correctness.** A number cited to a partially
   superseded circular (LH-608) passes.

## 5. Behaviour on the cases that decide the design

Each row is a test in `tests/test_assistant_answer.py`, and each changed the
parser rather than being written to fit it.

| Input shape | Treatment | Why |
|---|---|---|
| `[CIRC-2026-04@v2]` | Not a numeric claim | The marker contains 2026, 04 and 2. Scanning raw text flags every *correctly cited* sentence — a validator failing closed on good input, which gets switched off within a week |
| `"twelve point five percent"` | Numeric claim | Same claim as 12.5% with no digit. A model asked to write conversationally produces it |
| `"one of the documents"` | Not a claim | A number word with no quantity unit. Without this, nearly every English sentence is flagged and the first fix anyone reaches for is loosening the numeric check |
| `"the 15th of every month"` | Not a claim | When the EMI is due. Refusing it makes the commonest customer question unanswerable |
| `"Scheme 2020"` | Not a claim | A year in a name |
| `"₹2020"` | Claim | The year exemption is narrow: a currency prefix makes it an amount |
| `"₹1,50,000"` | Claim | Indian grouping. A thousands-separator regex misses the commonest way an Indian loan amount is written |
| `"between 8% and 12%"` | Two claims, one drop | Endpoint counting needs no understanding of range grammar |
| `"...1.5%. [CIRC@v2] The rate is 12.5%."` | Marker attaches to the *earlier* sentence | The subtlest defect found. Left on the later fragment, the fee sentence loses its source and the rate sentence gains one — an uncited number served under somebody else's citation. Finding P5-F2 |
| `[tool:compute_apr]` where no such tool is registered | Does not ground | Grounding is membership in the caller's allow-list, never the marker's shape |
| `[MADE-UP@v9]` | Does not ground, own verdict | A claimed source that does not exist is weaker evidence than no claim. Separate verdict so the audit can tell invention from omission |

## 6. Known limitations

* **Sentence splitting is punctuation-based** and mis-splits unlisted
  abbreviations. The failure direction is safe — a fragment has no citation and
  is dropped — but it produces mangled kept sentences, which is why `Rs.` and a
  short list of others are exempted. Every addition to that list makes the
  splitter less conservative.
* **Number words are bounded** at the magnitudes banking prose uses. Beyond
  "crore", a model writing digits is the overwhelmingly likelier case.
* **The spelled-number path takes one claim per sentence**, not all of them. It
  triggers a drop either way, so the count under-reports and the decision does
  not.
* **Devanagari and other scripts**: the danda (।) terminates a sentence, but
  number words in Hindi are not recognised. A spelled Hindi rate with no digit
  would pass. This is a real gap and it is not closable without the per-language
  work LH-610 scopes.
* **Over-refusal is not measured.** The conservative direction is fixed by
  design and Phase 5 §7 sets no target for it, so nothing here reports how often
  a good sentence is dropped. On a live system that number belongs beside the
  containment rate.

## 7. Monitoring

| Signal | Why |
|---|---|
| Sentences dropped per answer, by claim kind | A rising rate is a prompt or retrieval regression, not a validator one |
| Handoffs caused by total suppression | Distinguishes "lost a sentence" from "had nothing to say" |
| Unresolvable-citation verdicts | A model inventing citation ids is a specific, fixable prompt failure |
| Drops on Hindi and regional-language answers | The known gap above; a rate *lower* than English's is the suspicious direction |

`ValidatedAnswer.to_dict()` retains every dropped sentence verbatim, because the
weekly hallucination audit (SRS GA-6) needs the removed text — the surviving
text looks fine by construction.

## 8. Sign-off

| Field | Value |
|---|---|
| Developer | GenAI squad |
| Independent validation | **Not performed** — no validator assigned (Master §3.1) |
| Model Risk decision | **Not sought** |
| Compliance | **Not sought** — but note this component is what enforces the §8 do-not-invent rule on rates and fees |
