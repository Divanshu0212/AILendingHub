import type { Config } from "tailwindcss";

/**
 * Phase 7 §1 scope note: "Visual design (a component style guide,
 * color/typography, high-fidelity mockups) is a separate downstream design
 * workstream, not covered here."
 *
 * WHY THERE IS A PALETTE HERE ANYWAY, AND WHAT IT CLAIMS
 * ------------------------------------------------------
 * This build is presented at a TVS Credit hackathon, and an unstyled surface
 * communicates nothing about the system behind it. So a palette exists — and
 * it is scoped and labelled rather than smuggled in as if the phase had been
 * extended.
 *
 * The `brand` ramp below is **derived from TVS Credit's published brand
 * description**, not from TVS Credit's brand assets:
 *
 *   "Blue, derived from the identity of our parent group, stands for freedom,
 *    inspiration, confidence and stability. Green connotes growth, harmony and
 *    renewal."
 *      — tvscredit.com/about-us/know-our-brand
 *
 * The hex values are the ones published in third-party brand-asset indexes
 * (Venice Blue #0d4a85, Chathams Blue #174c82). **Nobody at TVS Credit approved
 * these**, no brand guideline document was consulted, and the AspireMark is not
 * reproduced anywhere in this build — a logo is the one asset a hackathon entry
 * must not fake, because a rendered mark reads as licensed use.
 *
 * Treat this as a presentation theme with a real citation, replaceable in one
 * file when the downstream design workstream ships an approved system.
 *
 * ACCESSIBILITY IS NOT DEFERRED
 * -----------------------------
 * Phase 7 §7 fixes WCAG 2.2 AA, and §8 makes the conformance level
 * non-negotiable per-surface. So every value below was contrast-checked against
 * its intended background before being written here, by computing the WCAG
 * relative-luminance ratio rather than by eye:
 *
 *   brand.700 #0d4a85 on white ............ 8.99:1  (AA text 4.5, AAA 7.0)
 *   brand.900 #0a3a68 on white ............ 11.55:1
 *   white on brand.700 .................... 8.99:1
 *   accent.600 #067647 on white ...........  5.69:1
 *   tier.red #b42318 on white .............  6.57:1
 *   tier.amber #b54708 on white ...........  5.43:1
 *   brand.100 on brand.900 (inverted UI) ..  8.93:1
 *
 * That is a computed check, not an audit: it covers text contrast and says
 * nothing about focus order, screen-reader labelling or reflow. The independent
 * audit Phase 7 §6 requires is still LH-710.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        /**
         * Blue — "freedom, inspiration, confidence and stability".
         * Derived from the published description; not an approved asset.
         */
        brand: {
          50: "#eef4fa",
          100: "#d6e4f2",
          200: "#adc9e5",
          300: "#7ba7d3",
          400: "#4a83bd",
          500: "#2166a3",
          600: "#174c82",
          700: "#0d4a85",
          800: "#0a3f70",
          900: "#0a3a68",
        },
        /** Green — "growth, harmony and renewal". */
        accent: {
          50: "#e8f5ef",
          100: "#c6e7d8",
          500: "#0a7d4a",
          600: "#067647",
          700: "#055c37",
        },
        // Semantic, not brand. An alert tier and a freshness state must be
        // visually distinguishable to satisfy the accessibility requirement;
        // these are unchanged from the pre-theme build.
        tier: {
          red: "#b42318",
          amber: "#b54708",
          none: "#475467",
        },
        fresh: {
          ok: "#067647",
          stale: "#b54708",
          unknown: "#475467",
        },
      },
      fontFamily: {
        // System stack only. A webfont is a network dependency and a licence
        // question, and TVS Credit's wordmark typeface is neither published nor
        // ours to embed.
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
