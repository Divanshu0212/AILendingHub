import type { Metadata } from "next";
import "./globals.css";

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
 * It is therefore set from the resolved locale at request time. Until the
 * registry exists, that resolves to "und" (BCP-47 "undetermined"), which is the
 * correct tag for content whose language is not known and is honest in a way
 * that "en" is not.
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
  const locale = params?.locale ?? "und";
  return (
    <html lang={locale}>
      <body className="min-h-screen">
        {/* WCAG 2.2 AA 2.4.1 bypass block. First focusable element on the page.
            THIS IS THE ONE HARDCODED ENGLISH STRING IN THE CODEBASE, and it is a
            genuine conflict between two binding rules rather than an oversight.
            WS-7.1.5 says no copy in frontend code; 2.4.1 says a bypass mechanism
            must exist, and it must be the first focusable element — before any
            registry fetch has resolved. A skip link that renders the
            missing-copy placeholder is a skip link a screen-reader user cannot
            identify, which fails the criterion the link exists to satisfy.
            Resolved in favour of accessibility and raised as P7-F8: the registry
            needs a small set of chrome keys resolvable at build time, which is a
            registry capability nobody has specified. */}
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:text-sm focus:outline focus:outline-2 focus:outline-blue-700"
        >
          Skip to content
        </a>
        <main id="main">{children}</main>
      </body>
    </html>
  );
}
