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
  const expectedKids = await page.evaluate(() => childAreas("GRP-CENTRAL").length);
  check("group lists its arcades", kids.length === expectedKids, `${kids.length} of ${expectedKids} children`);

  // --- the arcade a mall sits on counts the mall's points as its own
  const deep = await page.evaluate(() =>
    poisUnder("ARC-MARUGAMEMACHI", true).some((p) => p.id === "TEST-FLOOR"));
  check("descendant points roll up to the arcade", deep);

  // Drop the throwaway point now that the hierarchy checks above are done --
  // later checks (e.g. the mall-tap-area regression below) count real pois
  // per parent and would otherwise be thrown off by it.
  await page.evaluate(() => {
    const i = pois.findIndex((p) => p.id === "TEST-FLOOR");
    if (i >= 0) pois.splice(i, 1);
  });

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

  // --- tenants sharing a mall's placeholder coordinate (no known OSM
  // footprint, e.g. Youme Town) must not sit exactly on top of each other:
  // only the first would ever be visible or tappable, and a tap anywhere near
  // that point would always resolve to one specific tenant instead of the
  // mall. tools/add_pois.py spreads such groups apart; check the built data
  // actually reflects that, and that tapping the mall's own area (not a pin)
  // still opens the mall.
  const stackCheck = await page.evaluate(() => {
    const groups = new Map();
    for (const p of pois) {
      if (!p.parent) continue;
      const key = p.parent + "|" + p.coord.join(",");
      groups.set(key, (groups.get(key) || 0) + 1);
    }
    const worst = Math.max(0, ...groups.values());
    const mall = areas.find((a) => a.kind === "mall" && a.geometry &&
      poisUnder(a.id, false).length >= 3);
    if (!mall) return { worst, mallTap: null };
    const [lo, la] = mall.label_at || centerOfGeom(mall.geometry);
    const ring = mall.geometry.coordinates[0] || mall.geometry.coordinates[0][0];
    const corner = ring[0];
    view.cx = Proj.x(lo); view.cy = Proj.y(la); view.zoom = 17.5; clampView(); render();
    const [x, y] = toScreen(corner[0] * 0.6 + lo * 0.4, corner[1] * 0.6 + la * 0.4);
    return { worst, mallTap: hitTest(x, y), mallId: mall.id };
  });
  check("no two points under the same parent share one exact coordinate",
    stackCheck.worst <= 1, `worst group size: ${stackCheck.worst}`);
  check("tapping a mall's own area (not a pin) opens the mall",
    stackCheck.mallTap && stackCheck.mallTap.type === "area" && stackCheck.mallTap.id === stackCheck.mallId,
    JSON.stringify(stackCheck.mallTap));

  // --- a POI's breadcrumb must let you get back to its parent mall. Regression
  // test for a real bug: crumbHtml() always bolded (and made inert) the last
  // segment, which is correct for an area's own panel (the last segment IS
  // that page) but wrong for a POI's panel, where the crumb shows only
  // ancestor areas -- none of them is "the current page", so all of them,
  // including the immediate parent, should stay clickable.
  const poiWithParent = await page.evaluate(() => pois.find((p) => p.parent));
  await page.evaluate((id) => select({ type: "poi", id }, { fly: false }), poiWithParent.id);
  await page.waitForTimeout(200);
  const crumbLinks = await page.evaluate(() =>
    [...document.querySelectorAll("#sheetbody .crumb [data-goto]")].map((e) => e.dataset.goto));
  check("a POI's breadcrumb includes its immediate parent as a clickable link",
    crumbLinks.includes(poiWithParent.parent), JSON.stringify(crumbLinks));
  if (crumbLinks.length) {
    await page.click(`#sheetbody .crumb [data-goto='${crumbLinks[crumbLinks.length - 1]}']`);
    await page.waitForTimeout(200);
    const sel = await page.evaluate(() => selection);
    check("clicking a POI's breadcrumb navigates back to that area",
      sel && sel.type === "area" && sel.id === poiWithParent.parent, JSON.stringify(sel));
  }

  // --- the sheet's content scrolls by touch/drag on real overflow content.
  // Regression test for a real bug: #sheet had `touch-action: none`, which
  // (per spec) also silently overrides any touch-action a descendant sets,
  // so #sheetbody's native touch-scroll never actually worked on at least one
  // real Android device even though it looked fine in every desktop check.
  // Scrolling is now driven by JS pointer handlers instead of relying on
  // native touch-scroll at all -- this drags on #sheetbody itself, so a
  // regression back to "native scroll only" would fail here too.
  const scrollCase = await page.evaluate(() => {
    for (const a of areas) {
      select({ type: "area", id: a.id }, { fly: false });
      const el = document.getElementById("sheetbody");
      if (el.scrollHeight - el.clientHeight > 40) return { id: a.id, max: el.scrollHeight - el.clientHeight };
    }
    return null;
  });
  check("found a panel with real overflow to test scrolling", !!scrollCase, JSON.stringify(scrollCase));
  if (scrollCase) {
    await page.evaluate((id) => select({ type: "area", id }, { fly: false }), scrollCase.id);
    const box = await page.locator("#sheetbody").boundingBox();
    const vh = await page.evaluate(() => window.innerHeight);
    const yStart = Math.min(box.y + box.height, vh) - 20;
    const yEnd = box.y + 40;
    await page.mouse.move(box.x + box.width / 2, yStart);
    await page.mouse.down();
    for (let i = 1; i <= 12; i++) {
      await page.mouse.move(box.x + box.width / 2, yStart + (yEnd - yStart) * i / 12);
    }
    await page.mouse.up();
    await page.waitForTimeout(200);
    const scrolled = await page.evaluate(() => document.getElementById("sheetbody").scrollTop);
    check("dragging the sheet content scrolls it", scrolled > 0, `scrollTop=${scrolled} of max ${scrollCase.max}`);

    // A row is still tappable after scrolling (drag-to-scroll must not eat taps).
    await page.evaluate(() => { document.getElementById("sheetbody").scrollTop = 0; });
    const rowLocator = page.locator("#sheetbody [data-area],#sheetbody [data-poi]").first();
    if (await rowLocator.count()) {
      await rowLocator.click();
      await page.waitForTimeout(200);
      const sel = await page.evaluate(() => selection);
      check("a row is still tappable after enabling drag-scroll", !!sel, JSON.stringify(sel));
    }
  }

  // --- category filter hides pins
  const shown = await page.evaluate(() => {
    visibleCats = new Set(["transit"]);
    return pois.filter((p) => visibleCats.has(p.cat || "other")).length;
  });
  check("category filter narrows the visible pins", shown === 3, `${shown} transit pins`);

  // --- every point renders where it should regardless of which city it's
  // in. Regression test for a real, silent bug: the basemap's bbox (used by
  // clampView() as the pan boundary) only ever covered whichever single city
  // was passed as fetch_osm.py's primary argument. Centering the view on a
  // point in a second city, then clamping against a bbox that doesn't
  // include it, snapped the view back near the first city -- every point out
  // there rendered off-screen at a wrong pixel position, not "missing" so
  // much as silently mispositioned by tens of thousands of pixels. This
  // checks every point at least 2km from the default centre still lands
  // within a few pixels of screen centre once the view is centred on it.
  const farFlungCheck = await page.evaluate(() => {
    const [c0, c1] = meta.center;
    const farPois = pois.filter((p) => Math.hypot(p.coord[0] - c0, p.coord[1] - c1) > 0.02);
    return farPois.map((p) => {
      view.cx = Proj.x(p.coord[0]); view.cy = Proj.y(p.coord[1]); view.zoom = 16;
      clampView(); render();
      const [x, y] = toScreen(p.coord[0], p.coord[1]);
      return { id: p.id, name: p.name_zh, dx: Math.abs(x - W / 2), dy: Math.abs(y - H / 2) };
    });
  });
  const misplaced = farFlungCheck.filter((p) => p.dx > 5 || p.dy > 5);
  check(`all ${farFlungCheck.length} far-flung points render at their own screen centre`,
    farFlungCheck.length > 0 && misplaced.length === 0,
    misplaced.length ? JSON.stringify(misplaced) : `checked: ${farFlungCheck.map((p) => p.id).join(",")}`);

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
