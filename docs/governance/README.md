# Governance templates (WS-0.3.2)

Committed templates for every gate artifact:

| Template | Required by |
|---|---|
| [model_card_template.md](model_card_template.md) | Master §2 rule 5 — no model passes shadow without one |
| [validation_report_template.md](validation_report_template.md) | Master §3.1 — independent validation at every gate |
| [monitoring_plan_template.md](monitoring_plan_template.md) | SRS §11.1/§11.2 |
| Decision-log schema | Implemented as code: `lending_hub.decisionlog.DecisionRecord` |

The decision-log schema is deliberately **not** a markdown template. A schema that
lives in a document drifts from the schema that is written to disk, and the one
that matters is the second. `DecisionRecord` enforces its own completeness rules
in the constructor — a model decision must name its models, a human decision must
carry the override, and `policy_version` is mandatory.

## The model-risk policy itself

WS-0.3.1 requires a **ratified** SR 11-7-aligned model-risk policy: model
inventory, validation independence, model tiering. That document is not in this
repository, and writing a draft of it here would be the wrong move — a policy is
constituted by its ratification, not its text, and an unratified file in a code
repo invites exactly the "we have a policy" answer that a supervisor tests.

What this repository implements is the machinery the policy needs in order to
bite: the promotion gate (`lending_hub.mlops.promotion`) refuses production
without a model card, an independent validation report, four weeks of shadow, a
warm fallback, and current definitions. When the policy is ratified, its
thresholds configure that gate.

Tracked as **LH-160**.
