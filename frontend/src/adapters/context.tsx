"use client";

/**
 * The adapter and session context. One provider for all four surfaces.
 *
 * The default is `AbsentAdapter`, not a mock. A React context whose default
 * silently returns plausible data is how a screen that was never wired to the
 * gateway reaches a demo looking finished.
 */

import { createContext, useContext, type ReactNode } from "react";
import { AbsentAdapter, type Adapter } from "./port";
import type { Session } from "../lib/auth/session";

const AdapterContext = createContext<Adapter>(new AbsentAdapter());
const SessionContext = createContext<Session | null>(null);

export function AppProviders({
  adapter,
  session,
  children,
}: {
  adapter: Adapter;
  session: Session | null;
  children: ReactNode;
}) {
  return (
    <AdapterContext.Provider value={adapter}>
      <SessionContext.Provider value={session}>{children}</SessionContext.Provider>
    </AdapterContext.Provider>
  );
}

export function useAdapter(): Adapter {
  return useContext(AdapterContext);
}

export function useSession(): Session | null {
  return useContext(SessionContext);
}
