import type { Config } from "tailwindcss";

/**
 * Phase 7 §1 scope note: "Visual design (a component style guide,
 * color/typography, high-fidelity mockups) is a separate downstream design
 * workstream, not covered here."
 *
 * So this config deliberately defines no brand palette, no type scale and no
 * spacing system. It extends nothing. Components use Tailwind's stock neutral
 * ramp plus semantic aliases below, which exist only because an alert tier and a
 * freshness state must be visually distinguishable to satisfy the accessibility
 * requirement - not because anyone approved these colours.
 */
const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Semantic, not brand. Contrast ratios chosen against white/near-black
        // to clear WCAG 2.2 AA 4.5:1 for text; this has NOT been machine-verified
        // (no toolchain on the authoring machine) and is on the audit list.
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
    },
  },
  plugins: [],
};

export default config;
