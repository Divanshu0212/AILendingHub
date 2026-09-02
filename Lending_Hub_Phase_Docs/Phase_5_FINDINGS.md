# Phase 5 — implementation findings against the phase documents

Produced while building Phase 5. Master §1: "conflicts are raised as tickets,
never resolved silently by an implementer." Every finding below is **raised and
unapplied** — the SRS, the Master and the Phase 5 file are unchanged pending the
document owner's decision, as with the Phase 1, 2, 3 and 4 findings.

**Phase 5 is governed by one rule taken to its conclusion**: Master §2 rule 7,
LLM outputs are never facts. The phase file makes it the design centre, and the
findings below are almost all the same shape — the rule is stated, the mechanism
that would enforce it is named, and the *decision* that makes the mechanism act
is left unspecified. A guardrail that detects and does not decide is a log line.

That gives Phase 5's findings a different character from Phase 4's. P4's gaps
were values needed at the moment something is *done*. P5's are values needed at
the moment something is *refused* — and an unspecified refusal rule does not
fail closed, it fails silent.

## Status of each finding

| # | Finding | Kind | Ticket |
|---|---|---|---|
| P5-F1 | **"Tables kept intact" and the 800-token ceiling conflict**, and a split rate table fails silently with a real citation | **Deviation (deliberate)** | — |
| P5-F2 | **Effective dates cannot express partial supersession**, which is the common case for rate circulars | Gap found by building | **LH-608 (new)** |
| P5-F3 | **The injection defence detects and never decides** — no quarantine threshold, no response | Under-specification | **LH-607 (new)** |
| P5-F4 | **Conversational PII is not schema PII**, and Phase 0's column classification cannot govern prose | Gap found by building | **LH-606 (new)** |
| P5-F5 | **A per-language slice has no minimum size**, so a 20-triple slice reports in the same column as a 500-triple one | Gap found by building | **LH-610 (new)** |
| P5-F6 | **"A citation or a tool call" cannot distinguish a tool result from arithmetic on an unverified input** | Under-specification | **LH-611 (new)** |
| P5-F7 | **Per-session rate limits are required and unquantified**, with consequences in both directions | Under-specification | **LH-612 (new)** |
| P5-F8 | **LH-203 does not produce LH-603** — a letter sentence is not a conversational turn | Scope note | LH-603 |
| P5-F9 | **The uncited-numeric leak rate is structural, not measured**, and reads as evidence if quoted unqualified | Method note | — |

---

## A. Deviations — the spec's letter against its purpose

### A1 (P5-F1). A table kept intact will exceed the chunk ceiling

**§4 WS-5.1.2:** *"Structure-aware: headings respected, **tables kept intact**;
300–800 tokens per chunk."*

Two instructions that conflict on exactly the documents this phase exists to
serve. A bank rate circular's central artifact is a product-by-tenor rate table,
and such a table routinely exceeds 800 tokens on its own.

The conflict matters because of *how* the violation presents. A rate table split
across two chunks does not fail loudly:

- the half holding the header row retrieves for "what are the rates";
- the half holding the numbers retrieves for "12.5";
- each half is a fluent, well-formed passage.

What is lost is the association between them, so the model answers with a rate
from one product's row under another product's heading. That is **a wrong number
carrying a real citation to a real, currently-effective document** — the single
hardest error in this phase to detect after the fact, and the one that defeats
both the numeric-claim validator (the number *is* cited) and the faithfulness
scorer (the passage *does* contain it).

`chunk_document` therefore treats a table as atomic and emits an over-ceiling
chunk rather than splitting one, flagging it `oversize`. This is a deliberate
choice against the spec's letter in favour of its purpose, raised here rather
than made quietly — and the flag is reported rather than asserted on, because a
run with three oversize chunks is a fact about the corpus, not a failure.

**Recommended phase-file edit:** state the precedence — "tables are atomic; a
table chunk may exceed the ceiling and must be flagged" — so the retrieval and
embedding stages can be sized for it rather than discovering it in production.

---

## B. Gaps found by building — named mechanisms with no decision attached

### B1 (P5-F2). An effective date cannot express partial supersession

**§4 WS-5.1.1:** *"every policy circular, rate sheet, KFS template, FAQ gets
`{owner, effective-from, effective-to, version, product tags}` … Retrieval
filters to currently-effective documents by default."*

The filter is correct and insufficient. The common case in bank policy is not
replacement but **amendment in part**: circular B amends three clauses of
circular A and leaves the rest standing. Both are simultaneously effective, and
that is the accurate state of the world — A's unamended clauses *are* still
policy.

But nothing in `{effective_from, effective_to}` says which passage won:

- return both, and the model picks — the assistant asserts two rates;
- expire A wholesale, and its unamended clauses silently vanish from retrieval.

Neither is safe, and the phase file names neither. `registry` therefore models
supersession as a **declared relation** (`Document.supersedes`) that is recorded
and reported but never automatically acted on, and `conflicts()` surfaces the
pairs a human must rule on. The rule itself is **LH-608**, for Compliance and
Product.

### B2 (P5-F3). The injection defence detects and never decides

**§4 WS-5.4:** *"user input *and retrieved chunks* are untrusted; instruction/data
separation in prompts; tool calls outside the allow-list denied."*

The separation requirement is implementable and implemented — `UntrustedText`
makes the seam a type rather than a convention, so a prompt builder must unwrap
a retrieved chunk deliberately.

What is missing is everything after detection. `scan_for_injection` can score a
chunk; the phase file names **no score that quarantines it** and **no response
when one is found**. The three candidate responses are not variations in
strictness — they differ in who learns anything:

| Response | Customer sees | Anyone learns the corpus was poisoned |
|---|---|---|
| Drop the chunk silently | a normal answer | no |
| Drop and mark the answer | a marked answer | yes, eventually |
| Refuse the answer | a handoff | yes, immediately |

An implementer choosing here is choosing the bank's disclosure posture on a
security incident. Raised as **LH-607** rather than defaulted.

Related, and deliberate: `InjectionScan` reports **what matched** and never
returns a verdict of safety. Pattern matching catches the clumsy attack and
misses the careful one, so "no injection detected" would be the most dangerous
sentence this package could produce.

### B3 (P5-F4). Conversational PII is not schema PII

**§4 WS-5.4:** *"PII redaction before logging."*

Phase 0's LH-110 classified **table columns**. That artifact cannot govern this
one. A chat turn is free text in which a customer volunteers an Aadhaar number,
an account number, or a health reason for missing an instalment — and a column
classification tells a redactor nothing about what to look for in a sentence.

The third example is the one that makes this a policy question rather than a
regex question: a health disclosure is sensitive personal data under DPDP, it
appears in no schema, and no identifier format matches it.

The redactor covers unambiguous identifier formats, reports what it found, and
does not claim completeness. The class list is **LH-606**, for the DPO.

### B4 (P5-F5). A language slice has no minimum size

**§4 WS-5.3.4:** *"a language ships only when its slice passes the same gates as
English."* **SRS GA-4** requires Hindi plus two regional languages.

"The same gates" is a threshold, not a sample size, and the phase file states no
minimum for a slice. A 20-triple Hindi slice passing hit-rate@5 at 95% is four
misses and a coin flip — and it would appear in the same column, under the same
heading, as English's 500-triple result.

This is the golden-set analogue of a gate number computed on a sample too small
to carry it, and `goldenset.evaluate()` refuses to compute a hit-rate on a set
that fails admission for exactly this reason. The launch language list and the
per-slice minimum are **LH-610**.

### B5 (P5-F6). "A citation or a tool call" does not separate two different things

**§4 WS-5.3.1:** *"numeric values must come from a citation or a tool call."*
**§8:** rates and fees are retrieval/tool-only.

Read together these permit a tool-sourced EMI without a document citation, which
is right. But the answer contract cannot distinguish:

- `compute_emi` on a rate **retrieved from a currently-effective circular** — a
  grounded number; from
- `compute_emi` on a rate **the customer supplied in the previous turn** —
  arithmetic on an unverified input, wearing a tool's authority.

Both are "a tool call". The second is how an assistant ends up quoting a rate
the bank does not offer, in a sentence the validator passes. Whether a
tool-sourced number may be stated without a document citation, and how it must
be attributed, is **LH-611** for Compliance.

### B6 (P5-F7). Rate limits are required and unquantified

**§4 WS-5.4:** *"per-session rate limits."* No number.

The consequences run in both directions, which is what makes this a decision
rather than a tuning knob: too low and a customer comparing three tenors is
throttled mid-answer; too high and a scripted client walks the EMI grid until
the pricing model falls out of it.

`RateLimiter` takes the ceiling as a required argument and `launch_registry()`
supplies none, so the ceiling and its window are **LH-612**.

---

## C. Scope and method notes

### C1 (P5-F8). LH-203 does not produce LH-603

Both tickets are "reason-code wording", and it would be easy to close the second
by pointing at the first. They are different artifacts:

- **LH-203** (Phase 1) is one sentence per code in `config/reason_codes.yaml`,
  for an **adverse-action letter** — read once, with the letter's headers,
  footers and appeal instructions around it.
- **LH-603** (Phase 5) is a **conversational template set** — per-language
  variants, ordering rules, and the disclosures that must accompany an
  explanation given in a chat the customer can reply to.

A sentence approved for the first context is not approved for the second.
`templates` reads the LH-203 table for the code→feature mapping and still
refuses to render, which is the correct behaviour and worth stating so a future
reader does not treat ratifying LH-203 as unblocking this phase.

### C2 (P5-F9). The leak rate is a structural guarantee, not a measurement

**§7** makes **uncited-numeric leak rate = 0** a hard gate.

This repository satisfies it, and the way it satisfies it must travel with the
number. `validate()` drops uncited numeric claims and returns a `ValidatedAnswer`
rather than mutating a string, so the leak rate is zero **by construction** for
any answer that went through it. That is a property of the type, not a result of
an audit.

Three qualifications belong in the same breath, and the gate pack states them:

1. It guards **a code path, not a product** — an answer that bypassed
   `validate()` is outside the guarantee entirely.
2. It is a claim about **citation, not truth**. A cited number can be wrong if
   the citation is to a superseded circular (P5-F2) or the retrieval was
   poisoned (P5-F3).
3. §7 makes the leak rate a hard gate and **sets no target for over-refusal**.
   A validator that dropped every number would pass this gate perfectly and make
   the assistant useless, so the gate is one-sided by construction.

A structural guarantee quoted without its boundary reads as evidence. That is
the failure this note exists to prevent — the same shape as P4-F11 and P3's
in-sample comparison, and the reason the pack computes the claim by calling the
code it describes rather than typing the number.
