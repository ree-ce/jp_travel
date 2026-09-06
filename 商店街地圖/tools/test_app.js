// End-to-end checks for the built map: the behaviours SPEC.md promises, not
// just the first paint. Needs Playwright and a Chromium:
//
//     npm i playwright
//     node tools/test_app.js [path/to/takamatsu_map.html]
//
// Set PW_CHROMIUM to a browser binary if Playwright cannot find its own.
const path = require("path");
const { chromium, devices } = require("playwright");

const HTML = process.argv[2] || path.join(__dirname, "..", "takamatsu_map.html");
const FILE = "file://" + path.resolve(HTML);
const OUT = process.env.SHOT_DIR || path.join(__dirname, "..");

let pass = 0, fail = 0;
const check = (name, ok, extra) => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${extra ? "  " + extra : ""}`);
  ok ? pass++ : fail++;
};

(async () => {
  const browser = await chromium.launch(
    process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
  const ctx = await browser.newContext({ ...devices["iPhone 13"], hasTouch: true, isMobile: true });
  const page = await ctx.newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(e.message));
  page.on("console", (m) => m.type() === "error" && errs.push(m.text()));
  await page.goto(FILE, { waitUntil: "load" });
  await page.waitForTimeout(900);

  // --- hierarchy: mall -> arcade -> group, and the group lists its children
  // Inject a throwaway point under the mall rather than relying on whichever
  // real points ship in data/takamatsu.json at test time.
  await page.evaluate(() => {
    pois.push({ id: "TEST-FLOOR", name_zh: "測試樓層點", cat: "shop",
      coord: areaById.get("MALL-GREEN").label_at, parent: "MALL-GREEN", floor: "3F" });
    select({ type: "area", id: "MALL-GREEN" }, { fly: false });
  });
  await page.waitForTimeout(300);
  const crumb = await page.locator("#sheetbody .crumb").first().textContent();
  check("mall breadcrumb shows full ancestry", /高松中央商店街.*丸龜町商店街.*丸龜町 GREEN/s.test(crumb), crumb.trim());

  const floorRows = await page.evaluate(() =>
    [...document.querySelectorAll("#sheetbody .floor")].map((e) => e.textContent));
  check("points inside the mall are grouped by floor", floorRows.includes("3F"), JSON.stringify(floorRows));

  await page.click("#sheetbody .crumb [data-goto='GRP-CENTRAL']");
  await page.waitForTimeout(400);
  const kids = await page.evaluate(() =>
    [...document.querySelectorAll("#sheetbody [data-area]")].map((e) => e.dataset.area));
  check("group lists its arcades", kids.length === 8, `${kids.length} children`);

  // --- the arcade a mall sits on counts the mall's points as its own
  const deep = await page.evaluate(() =>
    poisUnder("ARC-MARUGAMEMACHI", true).some((p) => p.id === "TEST-FLOOR"));
  check("descendant points roll up to the arcade", deep);

  // --- navigation URL
  const href = await page.evaluate(() => {
    select({ type: "poi", id: "P005" }, { fly: false });
    return document.querySelector("#sheetbody a.btn.primary").href;
  });
  check("navigation link is a Google Maps walking directions URL",
    /^https:\/\/www\.google\.com\/maps\/dir\/\?api=1&destination=34\.\d+,134\.\d+&travelmode=walking$/.test(href), href);

  // --- search finds both areas and points, in Chinese and Japanese
  await page.fill("#q", "丸亀町");
  await page.waitForTimeout(300);
  const jaHits = await page.evaluate(() => ({
    areas: document.querySelectorAll("#sheetbody [data-area]").length,
    pois: document.querySelectorAll("#sheetbody [data-poi]").length,
  }));
  check("search matches the Japanese name", jaHits.areas >= 3, JSON.stringify(jaHits));
  await page.fill("#q", "高松站");
  await page.waitForTimeout(300);
  const zhHits = await page.evaluate(() =>
    document.querySelectorAll("#sheetbody [data-poi]").length);
  check("search matches the Chinese name", zhHits >= 1, `${zhHits} hit(s)`);
  await page.fill("#q", "");
  await page.waitForTimeout(200);

  // --- long press adds a point, and its parent is inferred from where it fell
  // Pick a spot that (a) isn't under a real POI pin -- hitTest deliberately
  // prefers points over areas -- and (b) hitTest itself resolves to
  // ARC-TAMACHI and not a neighbour. Arcades are curated as separate named
  // segments of one continuous street, so a segment's own endpoint can sit
  // exactly on the next segment's line too (distance 0 to both); a midpoint
  // of the segment stays unambiguously on this arcade alone.
  // Excludes the earlier in-memory TEST-FLOOR injection: refreshPois() (called
  // by the save handler below) rebuilds `pois` from CITY.pois + overrides and
  // drops it, which would otherwise net out against the point added here.
  const before = await page.evaluate(() => pois.filter((p) => p.id !== "TEST-FLOOR").length);
  const spot = await page.evaluate(() => {
    const a = areaById.get("ARC-TAMACHI");
    for (const ring of a.geometry.coordinates) {
      for (let i = 1; i < ring.length; i++) {
        const lo = (ring[i - 1][0] + ring[i][0]) / 2;
        const la = (ring[i - 1][1] + ring[i][1]) / 2;
        view.cx = Proj.x(lo); view.cy = Proj.y(la); view.zoom = 17.2;
        clampView(); render();
        const [x, y] = toScreen(lo, la);
        const clearOfPins = pois.every((p) => {
          const [px, py] = toScreen(p.coord[0], p.coord[1]);
          return Math.hypot(x - px, y - (py - 12)) > 40;
        });
        const resolves = JSON.stringify(hitTest(x, y)) === JSON.stringify({ type: "area", id: "ARC-TAMACHI" });
        if (clearOfPins && resolves) return { lo, la };
      }
    }
    return null;
  });
  check("found a tap spot clear of existing pins", !!spot, JSON.stringify(spot));
  await page.evaluate(({ lo, la }) => {
    view.cx = Proj.x(lo); view.cy = Proj.y(la); view.zoom = 17.2;
    clampView(); render();
  }, spot);
  const box = await page.locator("#map").boundingBox();
  await page.mouse.move(box.width / 2, box.height / 2);
  await page.mouse.down();
  await page.waitForTimeout(750);
  await page.mouse.up();
  await page.waitForTimeout(300);
  const parentSel = await page.locator("#f-parent").inputValue().catch(() => null);
  check("long press opens the add form", parentSel !== null);
  check("new point's area is inferred from the tap location",
    parentSel === "ARC-TAMACHI", String(parentSel));

  await page.fill("#f-name", "測試店家");
  await page.fill("#f-floor", "2F");
  await page.click("#f-save");
  await page.waitForTimeout(400);
  const after = await page.evaluate(() => pois.length);
  check("saving adds the point", after === before + 1, `${before} -> ${after}`);

  // --- the edit survives a reload (localStorage overlay)
  await page.reload({ waitUntil: "load" });
  await page.waitForTimeout(900);
  const survived = await page.evaluate(() =>
    pois.filter((p) => p.name_zh === "測試店家").map((p) => ({ parent: p.parent, floor: p.floor }))[0]);
  check("the point survives a reload", !!survived, JSON.stringify(survived));

  // --- export contains it, so it can go back into the repo
  const exported = await page.evaluate(() => {
    document.getElementById("btnLayers").click();
    document.getElementById("btn-export").click();
    return document.getElementById("out").value;
  });
  const parsed = JSON.parse(exported);
  const expectedAreas = await page.evaluate(() => areas.length);
  check("export round-trips through JSON",
    parsed.pois.some((p) => p.name_zh === "測試店家") && parsed.areas.length === expectedAreas,
    `${parsed.areas.length} areas (expected ${expectedAreas}), ${parsed.pois.length} points`);

  // --- category filter hides pins
  const shown = await page.evaluate(() => {
    visibleCats = new Set(["transit"]);
    return pois.filter((p) => visibleCats.has(p.cat || "other")).length;
  });
  check("category filter narrows the visible pins", shown === 3, `${shown} transit pins`);

  // --- no external requests: the whole point of the offline build
  const external = [];
  page.on("request", (r) => { if (!r.url().startsWith("file:")) external.push(r.url()); });
  await page.reload({ waitUntil: "load" });
  await page.waitForTimeout(1200);
  check("makes no network requests", external.length === 0, external.join(", "));

  check("no console errors", errs.length === 0, errs.join(" | "));
  if (process.env.SHOT_DIR) await page.screenshot({ path: path.join(OUT, "shot-interact.png") });
  console.log(`\n${pass} passed, ${fail} failed`);
  await browser.close();
  process.exit(fail ? 1 : 0);
})();
