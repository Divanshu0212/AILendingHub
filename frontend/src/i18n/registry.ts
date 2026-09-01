/**
 * WS-7.1.5 - the document-registry interface for UI copy.
 *
 * The registry itself is Module 6 / P5's corpus store and does not exist
 * (LH-701). This models the seam so that when it does, nothing in a component
 * changes: components already call `t(key)` and already handle the absence.
 *
 * WHY THIS IS A REGISTRY LOOKUP AND NOT A JSON BUNDLE
 * ---------------------------------------------------
 * A conventional i18n bundle ships copy inside the frontend build. That is fine
 * for chrome and wrong for disclosure: a Key Fact Statement or an APR sentence
 * that changes on a regulatory deadline would then require a frontend release,
 * and the release cadence of a mobile app is not the effective date of a
 * disclosure. Worse, the deployed bundle would carry a copy of the text with no
 * effective date attached, so nothing on the screen could say WHICH version of
 * the disclosure the customer was shown - which is precisely what a complaint
 * six months later turns on.
 *
 * So resolution is a runtime lookup that returns the document reference
 * alongside the text, and every rendered disclosure can name its source.
 */

import type { DocumentRef } from "../lib/gateway/types";

export interface ResolvedCopy {
  readonly key: string;
  readonly text: string;
  readonly source: DocumentRef;
}

/**
 * A key that could not be resolved. Rendered visibly rather than swallowed.
 *
 * `reason` distinguishes the three ways this happens, because they need three
 * different responses:
 *  - `no-registry`: the registry is not deployed. An environment problem.
 *  - `not-ratified`: the document exists and Compliance has not signed it. A
 *    governance state, and the correct behaviour is to block the screen rather
 *    than show the draft.
 *  - `no-translation`: ratified in some locale, absent in this one. A launch
 *    blocker for that language, and NOT a reason to fall back to another
 *    language - a Hindi customer shown an English APR sentence has been shown a
 *    disclosure they did not consent to receive in English.
 */
export interface MissingCopy {
  readonly key: string;
  readonly locale: string;
  readonly reason: "no-registry" | "not-ratified" | "no-translation";
  readonly ticket: string;
}

export type CopyResult = ResolvedCopy | MissingCopy;

export function isResolved(r: CopyResult): r is ResolvedCopy {
  return (r as ResolvedCopy).text !== undefined;
}

export interface CopyRegistry {
  /** Resolve one key in one locale. */
  resolve(key: string, locale: string): CopyResult;
  /** Which locales the registry can currently serve fully. */
  readonly availableLocales: readonly string[];
}

/**
 * The registry as this build has it: absent.
 *
 * Every lookup returns `no-registry`. This is not a stub waiting to be filled
 * with English - it is the honest state of a frontend built against a registry
 * that has not been created, and it makes the gap visible on every screen rather
 * than only in a document nobody opens.
 */
export class AbsentCopyRegistry implements CopyRegistry {
  readonly availableLocales: readonly string[] = [];

  resolve(key: string, locale: string): CopyResult {
    return { key, locale, reason: "no-registry", ticket: "LH-701" };
  }
}

/**
 * Gateway-backed registry. The shape the real one takes.
 *
 * Synchronous `resolve` over a preloaded snapshot rather than an async call per
 * key: a screen that awaits its own labels renders in stages, and a disclosure
 * banner that appears after the button it qualifies is a disclosure the customer
 * did not read. The snapshot is fetched once per locale per session, and its
 * `snapshotVersion` is recorded on any consent captured while it was current.
 */
export class SnapshotCopyRegistry implements CopyRegistry {
  constructor(
    private readonly entries: ReadonlyMap<string, ResolvedCopy>,
    readonly availableLocales: readonly string[],
    readonly snapshotVersion: string
  ) {}

  resolve(key: string, locale: string): CopyResult {
    const hit = this.entries.get(`${locale}::${key}`);
    if (hit) return hit;
    if (!this.availableLocales.includes(locale)) {
      return { key, locale, reason: "no-translation", ticket: "LH-707" };
    }
    return { key, locale, reason: "not-ratified", ticket: "LH-701" };
  }
}

/**
 * WS-7.1.5 coverage check, for CI.
 *
 * Localization parity is a Phase 7 §7 exit criterion ("localization parity
 * confirmed across all launch languages"), and parity is checkable mechanically:
 * every key in `ALL_COPY_KEYS` resolves in every launch locale. This returns the
 * gaps rather than a boolean, because "94 keys missing in one language" and "one
 * key missing in all four" are different problems.
 */
export function copyCoverageGaps(
  registry: CopyRegistry,
  keys: readonly string[],
  locales: readonly string[]
): readonly MissingCopy[] {
  const gaps: MissingCopy[] = [];
  for (const locale of locales) {
    for (const key of keys) {
      const r = registry.resolve(key, locale);
      if (!isResolved(r)) gaps.push(r);
    }
  }
  return gaps;
}
