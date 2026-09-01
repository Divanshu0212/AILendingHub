"use client";

/**
 * Shared component 7 of 7 (SRS §11.5) — the offer comparison table.
 *
 * Used by the customer app (WS-7.2.4, read-only) and the officer workbench
 * (WS-7.3.4, selectable). Phase 7 §4 WS-7.3.4 is explicit that these are the
 * "same constraint as the customer app, different write-permissions", so this is
 * one component with a `mode` prop rather than two tables that drift.
 *
 * EVERY NUMBER IN THIS TABLE IS A STRING FROM THE BACKEND
 * ------------------------------------------------------
 * There is no EMI calculation here. There is no total-payable column derived
 * from EMI × tenor. There is no APR. `reco.feasible.emi()` computes the EMI and
 * `reco.pricing.price()` computes the rate, both refusing without their ratified
 * inputs (LH-504, LH-505) — and the whole point of Phase 7 §8's rule is that the
 * frontend must not paper over that refusal with a formula anyone can write from
 * memory. The amortisation formula IS easy to write from memory. That is
 * precisely why it is on the do-not-invent list: an EMI computed here would be
 * right often enough that nobody would check it against the one in the loan
 * agreement.
 *
 * REJECTED OFFERS ARE SHOWN, WITH THEIR BINDING CONSTRAINT
 * --------------------------------------------------------
 * `reco.feasible.Assessment.binding_constraint` exists because "'declined' with
 * no reason is the shape of an adverse-action problem, and because an offer that
 * fails affordability by ₹200 and one that breaches a concentration cap are the
 * same boolean and entirely different conversations."
 *
 * A table that shows only the feasible offers throws that away. Worse, it makes
 * the feasible set look like the whole product catalogue, so nobody asks why the
 * larger loan is absent. This renders the rejected rows, greyed and
 * unselectable, each carrying its binding constraint's `detail`.
 *
 * THE RECOMMENDED OFFER IS MARKED, NOT REORDERED
 * ----------------------------------------------
 * When a bandit recommended a template, that row is marked. It is not moved to
 * the top and it is not pre-selected. `reco.bandit` logs a propensity because P6
 * reweights the decision; a UI that pre-selects the recommendation converts an
 * offer into a default, and a default's take-up rate measures the default rather
 * than the arm. The exploration flag is shown to officers for the same reason
 * `BanditDecision.is_exploration` exists — an officer overriding an exploration
 * arm should know it was one.
 */

import type { FeasibleSet, Offer, OfferAssessment } from "../../lib/gateway/types";
import { AuditLink } from "./AuditLink";
import { Copy } from "./Copy";

export type OfferTableMode = "read-only" | "selectable";

export function OfferComparisonTable({
  set,
  mode,
  selectedOfferId,
  onSelect,
  audience,
}: {
  set: FeasibleSet;
  mode: OfferTableMode;
  selectedOfferId: string | null;
  onSelect?: (offer: Offer) => void;
  audience: "customer" | "officer";
}) {
  const recommendedTemplate = set.recommendation?.templateId ?? null;

  if (set.isEmpty) {
    return (
      <div role="note" className="rounded border border-neutral-400 bg-neutral-50 p-4 text-sm">
        {/* An empty feasible set is a real, explainable state, not an error. The
            rejected rows below say why every candidate failed. */}
        <p className="mb-3">
          <Copy k="common.notAvailable" />
        </p>
        <RejectedList rejected={set.rejected} />
      </div>
    );
  }

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">
            <Copy k={audience === "customer" ? "customer.offers.title" : "workbench.offers.title"} />
          </caption>
          <thead>
            <tr className="border-b border-neutral-300 text-left text-xs uppercase tracking-wide text-neutral-500">
              {mode === "selectable" ? <th scope="col" className="p-2" /> : null}
              <th scope="col" className="p-2">
                product
              </th>
              <th scope="col" className="p-2">
                amount
              </th>
              <th scope="col" className="p-2">
                tenor
              </th>
              <th scope="col" className="p-2">
                rate
              </th>
              <th scope="col" className="p-2">
                EMI
              </th>
              <th scope="col" className="p-2">
                total interest
              </th>
              <th scope="col" className="p-2">
                model
              </th>
            </tr>
          </thead>
          <tbody>
            {set.feasible.map((offer) => {
              const isRecommended =
                recommendedTemplate !== null && offer.templateId === recommendedTemplate;
              return (
                <tr
                  key={offer.offerId}
                  className="border-b border-neutral-200"
                  data-offer-id={offer.offerId}
                  data-recommended={isRecommended}
                >
                  {mode === "selectable" ? (
                    <td className="p-2">
                      <input
                        type="radio"
                        name="offer"
                        value={offer.offerId}
                        checked={selectedOfferId === offer.offerId}
                        onChange={() => onSelect?.(offer)}
                        className="h-5 w-5"
                        aria-label={offer.offerId}
                      />
                    </td>
                  ) : null}
                  <td className="p-2 text-neutral-900">
                    {offer.product}
                    {isRecommended ? (
                      <span className="ml-2 rounded bg-blue-50 px-1.5 py-0.5 font-mono text-xs text-blue-900">
                        recommended
                      </span>
                    ) : null}
                    {isRecommended && audience === "officer" && set.recommendation?.isExploration ? (
                      <span className="ml-1 rounded bg-amber-50 px-1.5 py-0.5 font-mono text-xs text-amber-900">
                        exploration
                      </span>
                    ) : null}
                  </td>
                  {/* Every cell below renders `.display` — the string the
                      backend chose. `.amount` exists on these fields and is
                      never read here. */}
                  <td className="p-2 font-mono text-neutral-900">{offer.amount.display}</td>
                  <td className="p-2 font-mono text-neutral-900">{offer.tenorMonths}</td>
                  <td className="p-2 font-mono text-neutral-900">{offer.annualRate.display}</td>
                  <td className="p-2 font-mono text-neutral-900">{offer.emi.display}</td>
                  <td className="p-2 font-mono text-neutral-900">{offer.totalInterest.display}</td>
                  <td className="p-2">
                    <AuditLink attribution={offer.attribution} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {set.recommendation ? (
        <p className="mt-2 font-mono text-xs text-neutral-500">
          {/* Propensity is shown to officers because it is the number that makes
              the decision reweightable, and an officer choosing off-recommendation
              is creating exactly the log entry P6 reads. */}
          {audience === "officer"
            ? `propensity ${set.recommendation.propensity} · arms ${set.recommendation.consideredArms.length}`
            : null}
        </p>
      ) : null}

      {set.rejected.length > 0 ? (
        <details className="mt-4">
          <summary className="cursor-pointer text-sm text-neutral-700">
            {/* Rejected offers are behind a disclosure because they are
                secondary, NOT hidden: the summary states the count so the
                customer knows more were considered. */}
            <span className="font-mono">{set.rejected.length}</span>{" "}
            <Copy k="customer.offers.readOnlyNotice" />
          </summary>
          <div className="mt-2">
            <RejectedList rejected={set.rejected} />
          </div>
        </details>
      ) : null}
    </div>
  );
}

function RejectedList({ rejected }: { rejected: readonly OfferAssessment[] }) {
  return (
    <ul className="space-y-2">
      {rejected.map((a) => (
        <li
          key={a.offer.offerId}
          className="rounded border border-neutral-200 bg-white p-2 text-xs text-neutral-700"
          data-offer-id={a.offer.offerId}
          data-binding-constraint={a.bindingConstraintName ?? ""}
        >
          <span className="font-mono">
            {a.offer.product} &middot; {a.offer.amount.display} &middot; {a.offer.tenorMonths}
          </span>
          {/* `reason` is the backend's sentence from ConstraintResult.detail.
              Not reworded here — a rephrased decline reason is a decline reason
              nobody approved. */}
          <p className="mt-1 text-neutral-900">{a.reason}</p>
        </li>
      ))}
    </ul>
  );
}
