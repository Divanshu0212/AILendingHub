/**
 * One load, three outcomes, in one place.
 *
 * Every screen in this application does the same thing: call the adapter in an
 * effect, hold the result, hold an error. Eight pages had eight copies of that,
 * and the copies were identical — which was fine while there was one failure
 * state. There are now two, and they must be rendered differently:
 *
 *   `unavailable` — a 200 refusal carrying a ticket and an owner. Neutral
 *                   dashed frame. No retry affordance: retrying does not
 *                   ratify a policy value.
 *   `error`       — a transport failure, a 5xx, a missing attribution.
 *                   Red alert box. Retry is meaningful.
 *
 * Eight hand-written branches would be eight chances to put a governance stop
 * in the red box, and the one that got it wrong would look exactly like the
 * seven that got it right. So the branch lives here and the pages consume a
 * discriminated state.
 *
 * The cancellation guard is preserved from the pages this replaces: a fetch that
 * resolves after the component unmounts must not set state, and a filter changed
 * twice quickly must not have the first response overwrite the second.
 */

"use client";

import { useEffect, useState } from "react";

import { CapabilityUnavailableError } from "./unavailable";

export type LoadState<T> =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly data: T }
  | { readonly kind: "unavailable"; readonly error: CapabilityUnavailableError }
  | { readonly kind: "error"; readonly message: string };

/**
 * Run `load` when `deps` change and classify whatever comes back.
 *
 * `load` is not in the dependency array on purpose: an inline arrow passed by a
 * page is a new function every render, so depending on it would re-fetch
 * forever. `deps` is what the caller says actually changed — the same contract
 * `useEffect` itself has.
 */
export function useLoad<T>(load: () => Promise<T>, deps: readonly unknown[]): LoadState<T> {
  const [state, setState] = useState<LoadState<T>>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    load()
      .then((data) => {
        if (!cancelled) setState({ kind: "ready", data });
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        // The classification this hook exists for. `CapabilityUnavailableError`
        // is not a `GatewayError` subclass precisely so this check cannot be
        // satisfied by accident from the other branch.
        if (e instanceof CapabilityUnavailableError) {
          setState({ kind: "unavailable", error: e });
          return;
        }
        setState({ kind: "error", message: e instanceof Error ? e.message : String(e) });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
