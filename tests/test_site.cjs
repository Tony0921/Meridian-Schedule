const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { taipeiDate, weekDates, selectEvents, safeUrl, sourceUrl } = require("../site/app.js");
const members = require("./fixtures/data/members.json");
const schedule = require("./fixtures/data/schedule.json");

test("台灣日期不受執行電腦時區影響", () => {
  assert.equal(taipeiDate(new Date("2026-10-15T17:00:00Z")), "2026-10-16");
});
test("週一至週日支援跨年與週日", () => {
  assert.deepEqual(weekDates("2027-01-03"), ["2026-12-28", "2026-12-29", "2026-12-30", "2026-12-31", "2027-01-01", "2027-01-02", "2027-01-03"]);
});
test("今日依時間排序並保留取消狀態", () => {
  const events = selectEvents(schedule, members, "2026-10-16", "today");
  assert.deepEqual(events.map((event) => event.time), ["18:00", "20:00"]);
  assert.equal(events[0].status, "cancelled");
});
test("本週與單一成員篩選，待定時間排最後", () => {
  const events = selectEvents(schedule, members, "2026-10-16", "week", "demo-miri");
  assert.equal(events.length, 3);
  assert.equal(events.at(-1).time, null);
});
test("停用成員與無資料日期", () => {
  assert.equal(selectEvents(schedule, members.map((member) => ({ ...member, enabled: false })), "2026-10-16", "week").length, 0);
  assert.equal(selectEvents(schedule, members, "2030-01-01", "today").length, 0);
});
test("不允許腳本與不合法連結", () => {
  assert.equal(safeUrl("javascript:alert(1)"), null);
  assert.equal(safeUrl(null), null);
  assert.equal(safeUrl("https://example.com/live"), "https://example.com/live");
});
test("CSV 來源使用原始公開網址，舊資料只為數字 X ID 建立連結", () => {
  const event = { source_post_id: "csv-hash" };
  const member = { x_username: "OfficialMiri" };
  assert.equal(sourceUrl(event, member, { "csv-hash": "https://discord.com/channels/1/2/3" }), "https://discord.com/channels/1/2/3");
  assert.equal(sourceUrl(event, member), null);
  assert.equal(sourceUrl(event, member, { "csv-hash": "javascript:alert(1)" }), null);
  assert.equal(sourceUrl({ source_post_id: "123456789" }, member), "https://x.com/OfficialMiri/status/123456789");
  assert.equal(sourceUrl({ source_post_id: "demo-post" }, member), null);
});

test("未知行程的時間與徽章顯示未知，保留待定與休息的文字及排序", async () => {
  function element() {
    return {
      children: [], textContent: "", validity: { valid: true },
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this.children = children; },
      setAttribute() {}, addEventListener() {},
    };
  }
  const nodes = new Map(["#selected-date", "#member", "#schedule", "#message", "#today-view",
    "#week-view", "#updated-at", "#range-title"].map((selector) => [selector, element()]));
  const events = [["unknown", null], ["tbd", null], ["day_off", null], ["scheduled", "20:00"]]
    .map(([status, time]) => ({ ...schedule.events[0], id: status, date: taipeiDate(), status, time, platform: null }));
  const context = vm.createContext({
    URL,
    fetch: async (url) => ({ ok: true, json: async () => url.includes("members") ? members : { events } }),
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../site/app.js"), "utf8"), context);
  context.document = { querySelector: (selector) => nodes.get(selector), createElement: element };
  await vm.runInContext("startApp()", context);
  assert.equal(nodes.get("#message").textContent, "共 4 筆行程");
  const cards = nodes.get("#schedule").children[0].children.slice(1);
  assert.deepEqual(cards.map((card) => [card.children[0].textContent,
    card.children[1].children[2].children[0].textContent]), [
    ["20:00", "正常"], ["全天", "休息"], ["時間待定", "待定"], ["未知", "未知"],
  ]);
});

function themePage({ saved = null, dark = false, blockRead = false, blockWrite = false } = {}) {
  const document = new EventTarget();
  document.documentElement = { dataset: {} };
  const toggle = new EventTarget();
  toggle.checked = false;
  document.querySelector = () => toggle;
  const media = new EventTarget();
  media.matches = dark;
  const storage = new Map(saved === null ? [] : [["meridian-theme", saved]]);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../site/theme.js"), "utf8"), {
    document,
    window: { matchMedia: () => media },
    localStorage: {
      getItem(key) {
        if (blockRead) throw new Error("儲存空間無法讀取");
        return storage.get(key) ?? null;
      },
      setItem(key, value) {
        if (blockWrite) throw new Error("儲存空間無法寫入");
        storage.set(key, value);
      },
    },
  });
  const initialTheme = document.documentElement.dataset.theme;
  document.dispatchEvent(new Event("DOMContentLoaded"));
  return {
    root: document.documentElement, toggle, storage, initialTheme,
    changeSystem(value) {
      media.matches = value;
      media.dispatchEvent(new Event("change"));
    },
    changeToggle(value) {
      toggle.checked = value;
      toggle.dispatchEvent(new Event("change"));
    },
  };
}

test("首次載入在頁面內容出現前套用系統色系，無效偏好回到系統設定", () => {
  for (const [options, expected] of [
    [{}, "light"], [{ dark: true }, "dark"], [{ saved: "invalid", dark: true }, "dark"],
  ]) {
    const page = themePage(options);
    assert.equal(page.initialTheme, expected);
    assert.equal(page.toggle.checked, expected === "dark");
  }
});

test("手動切換深淺色並儲存，重新載入時優先採用使用者偏好", () => {
  const page = themePage();
  page.changeToggle(true);
  assert.equal(page.root.dataset.theme, "dark");
  assert.equal(page.storage.get("meridian-theme"), "dark");
  const reloaded = themePage({ saved: page.storage.get("meridian-theme") });
  assert.equal(reloaded.initialTheme, "dark");
  assert.equal(reloaded.toggle.checked, true);
  reloaded.changeToggle(false);
  assert.equal(reloaded.root.dataset.theme, "light");
  assert.equal(reloaded.storage.get("meridian-theme"), "light");
  assert.equal(themePage({ saved: "light", dark: true }).initialTheme, "light");
});

test("未手動選擇時即時跟隨系統，手動選擇後維持使用者色系", () => {
  const page = themePage();
  page.changeSystem(true);
  assert.equal(page.root.dataset.theme, "dark");
  assert.equal(page.toggle.checked, true);
  page.changeToggle(false);
  page.changeSystem(false);
  page.changeSystem(true);
  assert.equal(page.root.dataset.theme, "light");
  assert.equal(page.toggle.checked, false);
});

test("瀏覽器封鎖偏好讀取或寫入時仍可切換色系", () => {
  const page = themePage({ dark: true, blockRead: true, blockWrite: true });
  assert.equal(page.initialTheme, "dark");
  page.changeToggle(false);
  assert.equal(page.root.dataset.theme, "light");
  page.changeSystem(false);
  page.changeSystem(true);
  assert.equal(page.root.dataset.theme, "light");
  const readOnly = themePage({ saved: "light", dark: true, blockWrite: true });
  assert.equal(readOnly.initialTheme, "light");
  readOnly.changeToggle(true);
  assert.equal(readOnly.root.dataset.theme, "dark");
});
