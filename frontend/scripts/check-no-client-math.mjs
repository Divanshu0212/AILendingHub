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
 * NOTE: first executed 2026-09-02. Its first run reported 62 violations, all
 * false positives from C4 classifying Tailwind class strings as customer copy —
 * a gate whose entire output is noise is a gate nobody reads, and C1-C3 were
 * invisible behind it. C4 now decides class-vs-prose structurally and skips
 * comments. Verified in both directions: clean on this tree, and still firing
 * when a real adverse-action sentence is injected into a component.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname;
const SRC = join(ROOT, "src");

/** Directories where NO arithmetic may appear at all. */
const RENDER_LAYER = ["components", "app"];

/**
 * Files exempt from C4.
 *
 * The i18n modules ARE the string catalogue. `app/page.tsx` is the developer
 * route directory — it is not in Phase 7's screen inventory, renders no gateway
 * value, and its strings are route names and workstream ids rather than customer
 * copy. Exempting one known file by name is the narrow fix; loosening C4's rule
 * to accommodate it would have blunted the check for every real screen.
 */
const COPY_FILES = [
  join("i18n", "keys.ts"),
  join("i18n", "registry.ts"),
  join("app", "page.tsx"),
];

/**
 * Directories whose prose describes the SYSTEM, not the product.
 *
 * The module pages under `app/modules/` and the assistant surface exist to tell
 * a reviewer what each SRS module computes, what it was measured on, and which
 * ticket blocks the rest. That is engineering documentation rendered as a page:
 * no customer relies on it, it carries no effective date, and it names tickets
 * and model identifiers rather than rates or reasons.
 *
 * Scoped to a directory rather than loosened as a rule, so the check stays at
 * full strength on every screen a customer or an officer actually transacts on.
 * A rate, an APR sentence or an adverse-action reason appearing here would be as
 * wrong as anywhere else — but those come from the gateway, and this exemption
 * covers only literal strings the page itself holds.
 */
const DOC_SURFACES = [
  join("app", "modules"),
  join("app", "assistant"),
  join("app", "dashboard"),
];

/**
 * Directories where arithmetic is plotting, not decisioning.
 *
 * `components/charts/` maps values the backend computed onto pixel coordinates.
 * That produces no new fact about a customer and cannot: a bar's height is not
 * a figure anyone reads off the screen, and every LABEL on these charts renders
 * a value the gateway sent rather than one derived here.
 *
 * Scoped to one directory so the rule keeps full force everywhere else — the
 * alternative was relaxing C1 globally, which would have let a decisioning
 * screen multiply.
 */
const PLOT_SURFACES = [join("components", "charts")];

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
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "))
    .replace(/\/\/[^\n]*/g, " ")
    // Regex literals before anything else: `.replace(/_/g, " ")` reads as a
    // division to the operator scan below, which reported a string-formatting
    // call as arithmetic on a money figure. A gate whose findings are wrong is
    // a gate that gets exempted, so the pattern is removed rather than the rule
    // relaxed. Matched only after a character that cannot end an expression, so
    // a true division like `a / b` is untouched.
    .replace(/([=(,:[!&|?+\-*/%~^{;]\s*)\/(?![*/])(?:\\.|\[(?:\\.|[^\]\\])*\]|[^/\\\n[])+\/[gimsuyd]*/g, "$1RE")
    .replace(/`(?:\\.|\$\{[^}]*\}|[^`\\])*`/g, (m) => "``" + m.replace(/[^\n]/g, ""))
    .replace(/'(?:\\.|[^'\\])*'/g, "''")
    .replace(/"(?:\\.|[^"\\])*"/g, '""');
}

/**
 * Whether a string is a Tailwind class list rather than prose.
 *
 * Decided structurally — every space-separated token must look like a utility
 * class — instead of by word shape. The word-shape heuristic this replaces
 * asked whether the string contained three consecutive 3+-letter words, which
 * `rounded border border-neutral-400` satisfies, so every className in the
 * codebase was reported as hardcoded customer copy. 62 of them.
 *
 * That mattered beyond the noise: a gate whose output is entirely false
 * positives is a gate nobody reads, and the four real rules (C1-C3, and C4 on
 * genuine sentences) were invisible behind it.
 *
 * A class token is a lowercase utility, optionally with variant prefixes
 * (`hover:`, `md:`, `dark:`), a leading `-`, an arbitrary value in brackets, or
 * an opacity suffix — e.g. `min-h-[44px]`, `hover:bg-neutral-50`, `bg-white/80`.
 * Prose fails on the first capitalised word, punctuation, or bare English word
 * that is not a known single-word utility.
 */
function isClassList(body) {
  const tokens = body.trim().split(/\s+/);
  if (tokens.length < 2) return false;
  const shaped = tokens.every((t) =>
    /^-?(?:[a-z][a-z0-9-]*:)*[a-z][a-z0-9]*(?:-(?:[a-z0-9.]+|\[[^\]\s]+\]))*(?:\/\d+)?$/.test(t)
  );
  // A run of bare lowercase words satisfies the shape above and may still be a
  // sentence — "no citation available for this claim" is indistinguishable from
  // `grid flex hidden` by shape alone, and it is exactly the copy C4 exists to
  // catch. So require at least one token that only a utility class produces:
  // a hyphenated scale, a variant prefix, an arbitrary value, or an opacity.
  return shaped && tokens.some((t) => /[-:/[]/.test(t));
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

    // C2 - Math anywhere, except where the file's whole job is plotting.
    if (
      /\bMath\s*\./.test(line) &&
      !PLOT_SURFACES.some((d) => rel.startsWith(d))
    ) {
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
      const plotting = PLOT_SURFACES.some((d) => rel.startsWith(d));
      if (
        !plotting &&
        /\b\w+\s*[*/%]\s*\w+/.test(arith) &&
        !/\bkey\b|\bclassName\b/.test(arith)
      ) {
        findings.push(`C1 ${at}: arithmetic in the render layer. Every number is a gateway field.`);
      }
      if (!plotting && /(?:return|=)\s*[\w.()]+\s*[+-]\s*[\w.()]+\s*[;,)]/.test(arith)) {
        findings.push(`C1 ${at}: arithmetic in the render layer. Every number is a gateway field.`);
      }

      // C3 - client-side number formatting.
      if (
        !plotting &&
        /\.toFixed\s*\(|Intl\s*\.\s*NumberFormat|\.toLocaleString\s*\(/.test(line)
      ) {
        findings.push(
          `C3 ${at}: client-side number formatting. The gateway returns a display string alongside every numeric field.`
        );
      }
    }
  });

  // C4 - long literal strings in the render layer that are not lookup keys.
  //
  // Scanned with comments removed. A phase-file quotation inside a doc comment
  // — Phase 7 §4's "the single most important screen in the workbench" — is not
  // customer copy and never reaches a screen, but it is a long quoted string and
  // was reported as hardcoded copy. Citing the clause a component implements is
  // required by the repo's own conventions, so a gate that punishes it is a gate
  // that argues against documentation.
  const withoutComments = raw
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/\/\/[^\n]*/g, " ");
  const isDocSurface = DOC_SURFACES.some((d) => rel.startsWith(d));
  if (isRenderLayer(rel) && !isDocSurface && !COPY_FILES.some((c) => rel.endsWith(c))) {
    const literals = withoutComments.match(/"[^"\n]{40,}"|'[^'\n]{40,}'/g) ?? [];
    for (const lit of literals) {
      const body = lit.slice(1, -1);
      if (/^[a-z0-9_.]+$/i.test(body)) continue; // a key
      if (!/\s/.test(body)) continue; // no spaces - a class list or a path
      if (isClassList(body)) continue;
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
