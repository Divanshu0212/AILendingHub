import type { Metadata } from "next";
import { Inter_Tight, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

/**
 * Self-hosted via next/font rather than a <link> to Google.
 *
 * A stylesheet link in <head> is render-blocking and reaches a third party on
 * first paint; next/font inlines the face declarations and serves the files
 * from this origin, which also keeps the build free of an external dependency
 * at request time.
 */
const sans = Inter_Tight({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans-loaded",
  display: "swap",
});

const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-mono-loaded",
  display: "swap",
});

/**
 * Root layout for all four surfaces.
 *
 * The `lang` attribute is NOT hardcoded to a language. WCAG 2.2 AA 3.1.1
 * requires the page language to be programmatically determinable, and setting it
 * to "en" on a platform whose launch language list is unratified (LH-707) would
 * mislabel every non-English page — a screen reader would pronounce Hindi text
 * with English phonemes, which is a worse accessibility outcome than the missing
 * attribute this replaces.
 *
 * It is therefore set from the resolved locale at request time. That is now
 * `CHROME_LOCALE` ("en-IN"), because `i18n/chrome.ts` resolves the structural
 * labels in English and the tag must describe the text actually on screen. It
 * is NOT a claim that the platform launched in English: regulated copy still
 * resolves against the absent registry, and the launch language list is still
 * unratified (LH-707).
 */
export const metadata: Metadata = {
  title: "Lending Hub",
};

export default function RootLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params?: { locale?: string };
}) {
  // Chrome labels resolve in CHROME_LOCALE (see i18n/chrome.ts). Regulated copy
  // still resolves against the absent registry and renders its ticket, so this
  // tag describes the language of the text actually on screen.
  const locale = params?.locale ?? "en-IN";
  return (
    <html lang={locale} className={`${sans.variable} ${mono.variable}`}>
      <body className="min-h-screen">
        {/* WCAG 2.2 AA 2.4.1 bypass block. First focusable element on the page.
            THIS IS THE ONE HARDCODED ENGLISH STRING IN THE CODEBASE, and it is a
            genuine conflict between two binding rules rather than an oversight.
            WS-7.1.5 says no copy in frontend code; 2.4.1 says a bypass mechanism
            must exist, and it must be the first focusable element — before any
            registry fetch has resolved. A skip link that renders the
            missing-copy placeholder is a skip link a screen-reader user cannot
            identify, which fails the criterion the link exists to satisfy.
            Raised as P7-F8, whose stated resolution was "the registry needs a
            small set of chrome keys resolvable at build time". That set now
            exists as `i18n/chrome.ts`, so this link is the last remaining
            hardcoded string — it must render before any provider mounts, which
            is the one case a registry cannot serve. */}
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:text-sm focus:outline focus:outline-2 focus:outline-blue-700"
        >
          Skip to content
        </a>
        <Providers>
          <main id="main">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
