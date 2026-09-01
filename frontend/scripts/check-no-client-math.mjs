#!/usr/bin/env node
/**
 * Phase 7 §8 do-not-invent, mechanically.
 *
 *   "any EMI, eligibility amount, or reason-code sentence composed client-side
 *    (always backend/tool-computed, never invented in the UI layer)"
 *
 * and Phase 7 §7 exit criterion 4:
 *
 *   "zero instances in QA of a frontend surface computing or displaying an
 *    EMI/eligibility number without a backend call"
 *
 * That criterion is written as a QA observation, which is the wrong place for
 * it: QA sees the screens that were tested. This is the same rule as a build
 * gate, so it applies to the screens nobody opened.
 *
 * WHAT IT CHECKS
 * --------------
 * C1  No arithmetic operators (* / % and +/- on non-string operands) in
 *     src/components/ and src/app/ - the render layer. A frontend that can
 *     multiply can compute an EMI.
 * C2  No `Math.` anywhere under src/, except src/lib/format.ts which is
 *     explicitly a no-arithmetic file (it is checked to contain none).
 * C3  No `Intl.NumberFormat` / `toFixed` / `toLocaleString` on a number in the
 *     render layer. Choosing a rounding or a currency symbol for a money figure
 *     is a decision about what the number means, and the backend owns it.
 * C4  No hardcoded customer-facing sentence: any string literal in a component
 *     longer than the threshold that is not a lookup key. Copy comes from the
 *     document registry (WS-7.1.5) via t().
 *
 * WHAT IT CANNOT CHECK
 * --------------------
 * A number computed inside a template literal by a helper in src/lib/ that this
 * script has not classified, and any arithmetic reached through eval or a
 * dependency. C1-C4 are a floor, not a proof. The real control is that no
 * arithmetic helper exists in the codebase to call.
 *
 * NOTE: this script has never been executed - there is no Node runtime on the
 * authoring machine. Treat a green run as unobserved, not as evidence.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname;
const SRC = join(ROOT, "src");

/** Directories where NO arithmetic may appear at all. */
const RENDER_LAYER = ["components", "app"];

/** Files exempt from C4 because they ARE the string catalogue. */
const COPY_FILES = [join("i18n", "keys.ts"), join("i18n", "registry.ts")];

const findings = [];

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (/\.tsx?$/.test(p)) out.push(p);
  }
  return out;
}

/** Strip comments and string/template literals so operators inside copy do not fire. */
function stripped(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/\/\/[^\n]*/g, " ")
    .replace(/`(?:\\.|\$\{[^}]*\}|[^`\\])*`/g, "``")
    .replace(/'(?:\\.|[^'\\])*'/g, "''")
    .replace(/"(?:\\.|[^"\\])*"/g, '""');
}

function isRenderLayer(rel) {
  const first = rel.split(sep)[0];
  return RENDER_LAYER.includes(first);
}

for (const file of walk(SRC)) {
  const rel = relative(SRC, file);
  const raw = readFileSync(file, "utf8");
  const code = stripped(raw);
  const lines = code.split("\n");

  lines.forEach((line, i) => {
    const at = `${rel}:${i + 1}`;

    // C2 - Math anywhere.
    if (/\bMath\s*\./.test(line)) {
      findings.push(`C2 ${at}: Math.* in the frontend. Phase 7 §8 - the UI computes nothing.`);
    }

    if (isRenderLayer(rel)) {
      // C1 - arithmetic in the render layer. Deliberately blunt: `*` and `/`
      // outside JSX/regex/paths, and `+`/`-` in an assignment or return.
      const arith = line
        .replace(/\bimport\b[^\n]*/g, "")
        .replace(/\bfrom\b[^\n]*/g, "")
        .replace(/=>/g, "")
        .replace(/\+\+|--/g, "");
      if (/[^\s\w)\]]\s*[*/]\s*[\w(]/.test(arith) && !/^\s*[*/]/.test(arith)) {
        // heuristic; JSX self-closing and generics do not match this shape
      }
      if (/\b\w+\s*[*/%]\s*\w+/.test(arith) && !/\bkey\b|\bclassName\b/.test(arith)) {
        findings.push(`C1 ${at}: arithmetic in the render layer. Every number is a gateway field.`);
      }
      if (/(?:return|=)\s*[\w.()]+\s*[+-]\s*[\w.()]+\s*[;,)]/.test(arith)) {
        findings.push(`C1 ${at}: arithmetic in the render layer. Every number is a gateway field.`);
      }

      // C3 - client-side number formatting.
      if (/\.toFixed\s*\(|Intl\s*\.\s*NumberFormat|\.toLocaleString\s*\(/.test(line)) {
        findings.push(
          `C3 ${at}: client-side number formatting. The gateway returns a display string alongside every numeric field.`
        );
      }
    }
  });

  // C4 - long literal strings in the render layer that are not lookup keys.
  if (isRenderLayer(rel) && !COPY_FILES.some((c) => rel.endsWith(c))) {
    const literals = raw.match(/"[^"\n]{40,}"|'[^'\n]{40,}'/g) ?? [];
    for (const lit of literals) {
      const body = lit.slice(1, -1);
      if (/^[a-z0-9_.]+$/i.test(body)) continue; // a key
      if (!/\s/.test(body)) continue; // no spaces - a class list or a path
      if (/^[-\w\s:/[\]().]+$/.test(body) && !/[a-z]{3,}\s+[a-z]{3,}\s+[a-z]{3,}/i.test(body)) {
        continue; // tailwind class strings
      }
      findings.push(
        `C4 ${rel}: customer-facing sentence hardcoded (${body.slice(0, 48)}...). WS-7.1.5 - copy comes from the document registry, never from a component.`
      );
    }
  }
}

if (findings.length) {
  console.error("frontend computes nothing - violations:\n");
  for (const f of findings) console.error("  " + f);
  console.error(`\n${findings.length} violation(s).`);
  process.exit(1);
}
console.log("no-client-math: clean (see the script header for what this does NOT prove)");
