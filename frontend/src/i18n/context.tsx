"use client";

/**
 * WS-7.1.5 - the React seam for copy resolution.
 *
 * `t(key)` returns a `CopyResult`, never a string. That is deliberate friction:
 * a hook returning `string` would let a component write `t("x") || "Apply now"`,
 * and the fallback would be shipped English copy nobody ratified. Returning a
 * discriminated union forces every call site through `<Copy>`, which renders the
 * missing state visibly.
 */

import { createContext, useContext, type ReactNode } from "react";
import { AbsentCopyRegistry, type CopyRegistry, type CopyResult } from "./registry";

interface LocaleContextValue {
  readonly registry: CopyRegistry;
  readonly locale: string;
}

const LocaleContext = createContext<LocaleContextValue>({
  registry: new AbsentCopyRegistry(),
  locale: "und", // BCP-47 "undetermined". Not a default language - an admission.
});

export function LocaleProvider({
  registry,
  locale,
  children,
}: {
  registry: CopyRegistry;
  locale: string;
  children: ReactNode;
}) {
  return (
    <LocaleContext.Provider value={{ registry, locale }}>{children}</LocaleContext.Provider>
  );
}

export function useCopy(): (key: string) => CopyResult {
  const { registry, locale } = useContext(LocaleContext);
  return (key: string) => registry.resolve(key, locale);
}

export function useLocale(): string {
  return useContext(LocaleContext).locale;
}
