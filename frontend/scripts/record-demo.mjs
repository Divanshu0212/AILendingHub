/**
 * Record a ~90-second captioned walkthrough of the running frontend.
 *
 * WHAT THIS PRODUCES
 * ------------------
 * One .webm of a real browser driving the real application against the real
 * gateway. Nothing is staged: every number on screen came from the backend
 * during the recording, so a viewer is watching the system work rather than a
 * screen recording of a mockup.
 *
 * WHY CAPTIONS ARE BURNT IN RATHER THAN A SUBTITLE TRACK
 * -------------------------------------------------------
 * A .vtt file is the better format and the wrong choice here: the video will be
 * dropped into a slide, a chat window and possibly a form upload, and a
 * sidecar subtitle file survives none of those. An overlay injected into the
 * page is part of the pixels.
 *
 * The overlay is drawn in a fixed-position element with a `data-demo-overlay`
 * attribute so it cannot be confused with application chrome by anyone
 * inspecting the recording, and it is removed between scenes.
 *
 * PACING
 * ------
 * The target is around 90 seconds, and `hold` is not the whole cost of a scene:
 * navigation plus the settle wait adds roughly two and a half seconds that no
 * caption is up for, and a scrolling scene spends its hold in stepped
 * `evaluate` round-trips that overshoot it. Both are budgeted explicitly below
 * (`SETTLE_MS`, and the scroll branch spending exactly `hold`), and the script
 * prints measured wall-clock at the end rather than the sum of the holds — the
 * first cut ran 77s against a 56s estimate because it reported the latter.
 *
 * Within the budget the screens carrying charts and figures get the longest
 * holds; the ones whose point is a single refusal get less.
 *
 * Usage (needs the gateway on :8787 and the frontend on :3000):
 *   node frontend/scripts/record-demo.mjs               # writes reports/demo/
 *   node frontend/scripts/record-demo.mjs --out /tmp/x  # elsewhere
 */

import { chromium } from "playwright";
import { mkdirSync, renameSync, readdirSync, rmSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const BASE = process.env.DEMO_BASE ?? "http://localhost:3000";

// This script lives in `frontend/scripts/` because that is where its playwright
// dependency is installed — Node resolves packages from the script's own
// directory upward, not from the working directory. The default output is
// anchored to the repo root regardless, so `reports/demo/` means the same place
// whichever directory it is invoked from.
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const argOut = process.argv.indexOf("--out");
const OUT =
  argOut > -1
    ? resolve(process.argv[argOut + 1])
    : join(REPO_ROOT, "reports", "demo");

/** Time each scene waits after load for client-side fetches to land. */
const SETTLE_MS = 1200;

/**
 * Upper bound on the finished video, in seconds. Every scene's hold is spent
 * against it, and going over prints a warning rather than failing — the number
 * is a brief ("about a minute and a half"), not a contract.
 */
const BUDGET_S = 100;

/**
 * The walkthrough: every page in the dashboard's own navigation, in sidebar
 * order, with one exception.
 *
 * `hold` is milliseconds the caption stays up. `scroll` is a fraction of the
 * page to travel during the hold, so a long page reveals itself rather than
 * needing a second scene. `clicks` presses buttons by their accessible name.
 *
 * `/apply/APP-1/decision` is left out. It is behaving correctly — its subtitle
 * is a regulated copy key, so it renders `no-registry · LH-701` rather than
 * unratified customer-facing wording, and the decision body needs a backend
 * that does not exist. But a viewer cannot tell a principled refusal from a
 * broken screen in the two seconds it would be on camera, and the refusals
 * worth showing are the ones with something around them: the agri screen's
 * three raising derivations, the collections "not measurable" panel.
 */
const SCENES = [
  {
    path: "/workbench/queue",
    hold: 7000,
    scroll: 0.3,
    title: "Officer queue",
    caption: "Where an underwriter starts: real applications, real outcomes. There is no score column — the scorecard is not in the serving path, and an invented one would look exactly like a real one.",
  },
  {
    path: "/assistant/CONV-1",
    hold: 7500,
    scroll: 0.3,
    title: "Loan assistant",
    caption: "Every claim carries its source or is marked unverified. No language model is wired in: a corpus written by whoever grades the answers would only measure its own author.",
  },
  {
    path: "/dashboards/portfolio",
    hold: 9500,
    scroll: 0.55,
    title: "Risk & portfolio",
    caption: "Vintage curves, delinquency roll rates and IFRS 9 staging over a real 19-year US mortgage panel — 338,210 account-months, 827 defaults, 0.6967 out-of-sample c-index.",
  },
  {
    path: "/collections/queue",
    hold: 8500,
    scroll: 0.3,
    title: "Early warning",
    caption: "Does deterioration precede default? 82% of reachable defaults caught a median 6 months ahead; a tighter bar catches 56% at 5 months. Alert precision stays unmeasurable — it needs a collections desk.",
  },
  {
    path: "/dashboard",
    hold: 9000,
    // The one interactive screen. Without a click a viewer sees three buttons
    // and no output, which reads as a form that does nothing — so the demo
    // presses two of them and lets the real backend answers land on camera.
    clicks: ["Calculate instalment", "Find communities"],
    title: "Control centre",
    caption: "The engines run live. Instalment pricing and fraud-ring detection answer here on camera — computed by the backend on the inputs shown, never in the browser.",
  },
  {
    path: "/models",
    hold: 10500,
    scroll: 0.5,
    title: "19 models, 4 families",
    caption: "590,540 card transactions · 307,511 applications · 230,543 mortgage accounts · 147,409 crop pixels. Fraud reaches 0.9564 AUC. Zero models fitted on this bank's data — that column reads 0 on purpose.",
  },
  {
    path: "/modules/fraud/APP-1",
    hold: 7000,
    scroll: 0.3,
    title: "Fraud detection",
    caption: "Four layers, ordered by what each one needs to run. The ones that need a fraud desk's dispositions say so rather than scoring themselves.",
  },
  {
    path: "/modules/risk",
    hold: 7000,
    scroll: 0.3,
    title: "Default prediction",
    caption: "PD, LGD and EAD across the portfolio. Loss-given-default carries an open question about its own loss basis — it flips the sign of a coefficient on real data.",
  },
  {
    path: "/modules/agri/PLOT-DEMO-1",
    hold: 7000,
    scroll: 0.25,
    title: "Agricultural intelligence",
    // The only illustrative screen in the build, and the caption says so
    // rather than leaving it to the banner — the banner scrolls, the caption
    // does not, and a viewer who reads only one of the two must not come away
    // thinking this plot is real.
    caption: "The one illustrative screen in the build — no satellite imagery for Indian smallholdings exists on any track. Yield, income and land quality all refuse to compute, each naming the decision it waits on.",
  },
];

/**
 * Injected into the page, as a real function rather than a string.
 *
 * Both details here were bugs first. `page.evaluate` given a *string* runs it
 * as an expression, not as a callable — so a stringified arrow evaluates to a
 * function object, ignores the argument and returns undefined, producing no
 * overlay and no error. And it passes exactly one argument, so a four-parameter
 * signature takes an array as its first parameter and undefined for the rest.
 * Neither failure throws; both are invisible until someone watches the video,
 * which is why `main` asserts the caption actually rendered.
 */
function overlay({ title, caption, index, total }) {
  document.querySelector("[data-demo-overlay]")?.remove();
  const el = document.createElement("div");
  el.setAttribute("data-demo-overlay", "true");
  // A solid, self-sizing band rather than a fixed-height gradient. The
  // gradient version let a three-line caption wrap out through its own fade
  // and across the sidebar, so the longest captions were the ones that looked
  // broken — exactly the scenes with the most to say.
  el.style.cssText = [
    "position:fixed", "left:0", "right:0", "bottom:0", "z-index:2147483647",
    "padding:16px 32px 18px",
    "background:rgba(8,20,33,0.94)",
    "backdrop-filter:blur(3px)",
    "box-shadow:0 -18px 34px rgba(8,20,33,0.42)",
    "font-family:'Inter Tight',system-ui,sans-serif", "pointer-events:none",
    "animation:demoIn .32s ease-out",
  ].join(";");
  const style = document.createElement("style");
  style.textContent =
    "@keyframes demoIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}";
  el.appendChild(style);

  const row = document.createElement("div");
  row.style.cssText = "display:flex;align-items:baseline;gap:12px;margin-bottom:5px";
  const num = document.createElement("span");
  num.textContent = String(index).padStart(2, "0") + " / " + String(total).padStart(2, "0");
  num.style.cssText =
    "font-family:ui-monospace,monospace;font-size:11px;letter-spacing:.1em;color:#6ea8e8";
  const h = document.createElement("span");
  h.textContent = title;
  h.style.cssText = "font-size:20px;font-weight:600;color:#fff;letter-spacing:-0.01em";
  row.append(num, h);

  const p = document.createElement("p");
  p.textContent = caption;
  p.style.cssText =
    "margin:0;font-size:14.5px;line-height:1.45;color:#cbdcee;max-width:1290px";

  el.append(row, p);
  document.body.appendChild(el);
}

async function main() {
  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(OUT, { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    recordVideo: { dir: OUT, size: { width: 1440, height: 900 } },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  const started = Date.now();
  for (const [i, scene] of SCENES.entries()) {
    const sceneStart = Date.now();
    process.stdout.write(`  ${i + 1}/${SCENES.length}  ${scene.path}`);

    // No transition cover here, deliberately. An earlier cut faded a navy
    // panel in before each `goto` to hide the blank shell between scenes. It
    // made things worse: the cover does not survive the navigation (measured —
    // zero cover elements in the new document), so all it added was its own
    // 240ms of flat colour on top of the gap it was hiding. These pages reach
    // full content about 20ms after `goto` resolves, so the honest fix was to
    // wait for content and drop the theatre.
    await page.goto(BASE + scene.path, { waitUntil: "networkidle", timeout: 45000 });
    // Clear the previous scene's height sample. It would otherwise let the
    // two-agreeing-samples check pass on its first poll against a stale value.
    await page.evaluate(() => {
      delete window.__demoPainted;
    });
    // Wait for the client-side fetches to land before the caption claims what
    // is on screen. `networkidle` is not enough: these pages fetch after
    // hydration, so early cuts caught the agri page mid-"Loading" and the
    // portfolio page as a bare shell — a rendered sidebar and an empty content
    // column, which shows no "Loading" text to test for.
    //
    // So the wait is on the content column being *laid out*, not merely
    // populated. Text length alone is not enough — `innerText` reports content
    // the browser has not painted yet, which is how a bare-shell frame reached
    // the recording with the check passing. Requiring the element to have real
    // height as well ties the wait to layout, and two consecutive agreeing
    // samples rule out catching it mid-paint.
    await page
      .waitForFunction(
        () => {
          const main = document.querySelector("main") ?? document.body;
          const text = main.innerText.trim();
          if (text.length < 400 || /^Loading/.test(text)) return false;

          // Count laid-out descendants rather than measuring the container.
          // The container is full height even while empty — that is how a
          // bare-shell portfolio frame passed a height check — so the real
          // signal is how many elements actually occupy space inside it.
          const painted = Array.from(main.querySelectorAll("*")).filter((el) => {
            const r = el.getBoundingClientRect();
            return r.width > 40 && r.height > 12;
          }).length;
          if (painted < 25) return false;

          const w = window;
          const prev = w.__demoPainted;
          w.__demoPainted = painted;
          return prev === painted;
        },
        undefined,
        { timeout: 20000, polling: 120 }
      )
      .catch(() => {});
    await page.waitForTimeout(SETTLE_MS);

    const contentLength = await page.evaluate(() => {
      const main = document.querySelector("main") ?? document.body;
      return main.innerText.trim().length;
    });
    if (contentLength < 400) {
      throw new Error(
        `${scene.path} rendered only ${contentLength} chars — still a shell`
      );
    }
    await page.evaluate(overlay, {
      title: scene.title,
      caption: scene.caption,
      index: i + 1,
      total: SCENES.length,
    });
    // Prove the overlay actually rendered. It failed silently once (a
    // four-arg signature against evaluate's single argument), and an
    // uncaptioned demo is the whole deliverable missing.
    const shown = await page.evaluate(
      () => document.querySelector("[data-demo-overlay] p")?.textContent ?? ""
    );
    if (shown !== scene.caption) {
      throw new Error(`caption did not render on ${scene.path}: got "${shown}"`);
    }

    if (scene.clicks) {
      // Split the hold across the clicks so each result is on screen long
      // enough to read. A click that finds no button is a scene quietly
      // showing nothing, so it fails loudly instead.
      const slice = scene.hold / (scene.clicks.length + 1);
      await page.waitForTimeout(slice);
      for (const label of scene.clicks) {
        const button = page.getByRole("button", { name: label });
        if ((await button.count()) === 0) {
          throw new Error(`no button "${label}" on ${scene.path}`);
        }
        await button.first().click();
        await page.waitForTimeout(slice);
      }
    } else if (scene.scroll) {
      // Spend exactly `hold` on the scene: hold the top for a quarter of it so
      // the caption and the headings are readable together, then travel. Each
      // step's wait is trimmed by the round-trip it just cost, so the scene
      // lands on its budget instead of drifting past it.
      const height = await page.evaluate(() => document.body.scrollHeight);
      const target = (height - 900) * scene.scroll;
      const lead = scene.hold * 0.25;
      await page.waitForTimeout(lead);
      const steps = 20;
      const budget = (scene.hold - lead) / steps;
      for (let s = 1; s <= steps; s += 1) {
        const t0 = Date.now();
        await page.evaluate((y) => window.scrollTo(0, y), (target / steps) * s);
        const rest = budget - (Date.now() - t0);
        if (rest > 0) await page.waitForTimeout(rest);
      }
    } else {
      await page.waitForTimeout(scene.hold);
    }
    process.stdout.write(`  (${((Date.now() - sceneStart) / 1000).toFixed(1)}s)\n`);
  }
  const elapsed = (Date.now() - started) / 1000;

  await context.close();
  await browser.close();

  const file = readdirSync(OUT).find((f) => f.endsWith(".webm"));
  if (file) {
    renameSync(join(OUT, file), join(OUT, "lending-hub-demo.webm"));
    console.log(`\n  wrote ${join(OUT, "lending-hub-demo.webm")}`);
    console.log(`  ${SCENES.length} scenes, ${elapsed.toFixed(1)}s measured`);
    if (elapsed > BUDGET_S) {
      console.log(`  WARNING: over the ${BUDGET_S}s budget — trim a hold`);
    }
  } else {
    console.error("no video written — did the browser close cleanly?");
    process.exit(1);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
