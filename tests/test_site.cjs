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
  const events = selectEvents(schedule, members, "2026-10-16", "week", new Set(["demo-miri"]));
  assert.equal(events.length, 3);
  assert.equal(events.at(-1).time, null);
});
test("事件狀態可複選，並維持日期、成員與排序條件", () => {
  const statuses = new Set(["scheduled", "day_off"]);
  const events = selectEvents(schedule, members, "2026-10-16", "week", null, statuses);
  assert.deepEqual(events.map((event) => event.id), [
    "demo-miri-20261016-2000-001", "demo-miri-20261017-2200-001", "demo-snow-20261017-off-001",
  ]);
  assert.equal(selectEvents(schedule, members, "2026-10-16", "today", null, statuses).length, 1);
  assert.deepEqual(selectEvents(schedule, members, "2026-10-16", "week", new Set(["demo-snow"]), statuses)
    .map((event) => event.id), ["demo-snow-20261017-off-001"]);
});
test("未勾選任何事件狀態或狀態無符合行程時回傳空清單", () => {
  for (const statuses of [new Set(), new Set(["live"])]) {
    assert.deepEqual(selectEvents(schedule, members, "2026-10-16", "week", null, statuses), []);
  }
});

test("成員集合支援複選，空集合不等同所有成員", () => {
  const selected = new Set(["demo-miri", "demo-snow", "missing"]);
  assert.deepEqual(selectEvents(schedule, members, "2026-10-16", "today", selected)
    .map((event) => event.member_id), ["demo-snow", "demo-miri"]);
  assert.deepEqual(selectEvents(schedule, members, "2026-10-16", "week", new Set()), []);
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

async function schedulePage(events = [], {
  pageMembers = members, saved = null, blockRead = false, blockWrite = false,
} = {}) {
  function element() {
    const attributes = new Map();
    return Object.assign(new EventTarget(), {
      children: [], textContent: "", checked: false, disabled: false, validity: { valid: true },
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this.children = children; },
      setAttribute(name, value) { attributes.set(name, value); },
      getAttribute(name) { return attributes.get(name) ?? null; },
    });
  }
  const nodes = new Map(["#selected-date", "#schedule", "#message", "#today-view", "#date-view",
    "#week-view", "#updated-at", "#range-title", "#status-filters", "#status-options",
    "#all-members", "#group-options", "#member-options"]
    .map((selector) => [selector, element()]));
  const storage = new Map(saved === null ? [] : [["meridian-members", saved]]);
  nodes.storage = storage;
  const context = vm.createContext({
    URL,
    fetch: async (url) => ({ ok: true, json: async () => url.includes("members") ? pageMembers : { events } }),
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
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../site/app.js"), "utf8"), context);
  context.document = { querySelector: (selector) => nodes.get(selector), createElement: element };
  await vm.runInContext("startApp()", context);
  return nodes;
}

const filterMembers = [
  members[0],
  { ...members[1], group: "alpha", group_name: "團體 A" },
  { ...members[1], id: "alpha-two", name: "A2", group: "alpha", group_name: "團體 A" },
  { ...members[1], id: "beta-one", name: "B1", group: "beta", group_name: "團體 B" },
  { ...members[1], id: "beta-two", name: "B2", group: "beta", group_name: "團體 B" },
  { ...members[1], id: "guest", name: "合作成員", group: "collaborators", group_name: "合作藝人" },
  { ...members[1], id: "disabled-alpha", group: "alpha", group_name: "團體 A", enabled: false },
  { ...members[1], id: "disabled-only", group: "empty", group_name: "無啟用成員", enabled: false },
];

function inputs(nodes, selector) {
  return nodes.get(selector).children.map((label) => label.children[0]);
}

function selectedMembers(nodes) {
  return inputs(nodes, "#member-options").filter((input) => input.checked).map((input) => input.value);
}

function checkOption(nodes, selector, value, checked) {
  const input = inputs(nodes, selector).find((item) => item.value === value);
  assert.ok(input, `應提供 ${selector} 的 ${value} 選項`);
  input.checked = checked;
  input.dispatchEvent(new Event("change"));
}

test("第一次開啟全選，團體排除 none、停用與零啟用成員的選項", async () => {
  const nodes = await schedulePage([], { pageMembers: filterMembers });
  assert.deepEqual(selectedMembers(nodes), ["demo-miri", "demo-snow", "alpha-two", "beta-one", "beta-two", "guest"]);
  const groups = inputs(nodes, "#group-options");
  assert.deepEqual(groups.map((input) => input.value), ["alpha", "beta", "collaborators"]);
  assert.ok(groups.every((input) => input.checked));
  assert.equal(nodes.get("#all-members").checked, true);
  const empty = await schedulePage([], { pageMembers: filterMembers.map((member) => ({ ...member, enabled: false })) });
  assert.equal(inputs(empty, "#group-options").length, 0);
  assert.equal(empty.get("#all-members").checked, false);
});

test("勾選團體以已選團體聯集取代成員選取，清除其他手動成員", async () => {
  const nodes = await schedulePage([], { pageMembers: filterMembers, saved: "[]" });
  checkOption(nodes, "#member-options", "demo-miri", true);
  checkOption(nodes, "#group-options", "alpha", true);
  assert.deepEqual(selectedMembers(nodes), ["demo-snow", "alpha-two"]);
  checkOption(nodes, "#member-options", "demo-miri", true);
  checkOption(nodes, "#group-options", "beta", true);
  assert.deepEqual(selectedMembers(nodes), ["demo-snow", "alpha-two", "beta-one", "beta-two"]);
  assert.deepEqual(inputs(nodes, "#group-options").filter((input) => input.checked).map((input) => input.value), ["alpha", "beta"]);
});

test("取消團體只移除該團體成員，其他手動選取保留且可繼續自由勾選", async () => {
  const nodes = await schedulePage([], { pageMembers: filterMembers, saved: '["demo-miri","demo-snow","alpha-two","beta-one"]' });
  checkOption(nodes, "#group-options", "alpha", false);
  assert.deepEqual(selectedMembers(nodes), ["demo-miri", "beta-one"]);
  assert.ok(inputs(nodes, "#group-options").every((input) => !input.checked));
  checkOption(nodes, "#member-options", "alpha-two", true);
  assert.deepEqual(selectedMembers(nodes), ["demo-miri", "alpha-two", "beta-one"]);
});

test("成員選滿自動勾選團體及全選，少一人即取消", async () => {
  const nodes = await schedulePage([], { pageMembers: filterMembers, saved: "[]" });
  for (const id of ["demo-snow", "alpha-two"]) checkOption(nodes, "#member-options", id, true);
  const alpha = inputs(nodes, "#group-options").find((input) => input.value === "alpha");
  assert.equal(alpha.checked, true);
  assert.equal(nodes.get("#all-members").checked, false);
  for (const id of ["demo-miri", "beta-one", "beta-two", "guest"]) checkOption(nodes, "#member-options", id, true);
  assert.equal(nodes.get("#all-members").checked, true);
  checkOption(nodes, "#member-options", "demo-snow", false);
  assert.equal(alpha.checked, false);
  assert.equal(nodes.get("#all-members").checked, false);
});

test("全選可清空與恢復所有成員及團體，並即時篩選行程而不改事件狀態", async () => {
  const events = members.map((member) => ({ ...schedule.events[0], id: member.id, member_id: member.id, date: taipeiDate() }));
  const nodes = await schedulePage(events, { pageMembers: filterMembers });
  assert.equal(nodes.get("#message").textContent, "共 2 筆行程");
  checkOption(nodes, "#member-options", "demo-snow", false);
  assert.equal(nodes.get("#message").textContent, "共 1 筆行程");
  const all = nodes.get("#all-members");
  all.checked = false;
  all.dispatchEvent(new Event("change"));
  assert.deepEqual(selectedMembers(nodes), []);
  assert.ok(inputs(nodes, "#group-options").every((input) => !input.checked));
  assert.equal(nodes.get("#message").textContent, "請至少勾選一位 VTuber。");
  assert.equal(nodes.get("#schedule").children[0].children[1].className, "empty-day");
  assert.ok(inputs(nodes, "#status-options").every((input) => input.checked));
  all.checked = true;
  all.dispatchEvent(new Event("change"));
  assert.equal(selectedMembers(nodes).length, 6);
  assert.ok(inputs(nodes, "#group-options").every((input) => input.checked));
  assert.equal(nodes.get("#message").textContent, "共 2 筆行程");
});

test("偏好重載恢復成員與團體，全部取消也會保存", async () => {
  const nodes = await schedulePage([], { pageMembers: filterMembers, saved: "[]" });
  checkOption(nodes, "#group-options", "alpha", true);
  let restored = await schedulePage([], { pageMembers: filterMembers, saved: nodes.storage.get("meridian-members") });
  assert.deepEqual(selectedMembers(restored), ["demo-snow", "alpha-two"]);
  assert.equal(inputs(restored, "#group-options")[0].checked, true);
  restored.get("#all-members").checked = false;
  restored.get("#all-members").dispatchEvent(new Event("change"));
  restored = await schedulePage([], { pageMembers: filterMembers, saved: restored.storage.get("meridian-members") });
  assert.deepEqual(selectedMembers(restored), []);
  assert.equal(restored.get("#all-members").checked, false);
});

test("恢復偏好忽略停用或移除成員，新成員不自動勾選", async () => {
  const nodes = await schedulePage([], { pageMembers: filterMembers, saved: '["demo-miri","demo-snow","removed","disabled-alpha"]' });
  assert.deepEqual(selectedMembers(nodes), ["demo-miri", "demo-snow"]);
  assert.equal(nodes.get("#all-members").checked, false);
  assert.equal(inputs(nodes, "#group-options")[0].checked, false);
});

test("首次未操作篩選也保存當下名單，之後新增成員不自動勾選", async () => {
  const first = await schedulePage();
  assert.deepEqual(JSON.parse(first.storage.get("meridian-members") ?? "null"), ["demo-miri", "demo-snow"]);
  const reloaded = await schedulePage([], { pageMembers: filterMembers, saved: first.storage.get("meridian-members") });
  assert.deepEqual(selectedMembers(reloaded), ["demo-miri", "demo-snow"]);
  assert.equal(reloaded.get("#all-members").checked, false);
});

test("損壞偏好回到全選，儲存讀寫遭封鎖時仍可使用篩選", async () => {
  for (const saved of ["invalid", "null", "{}", '["demo-miri",1]']) {
    const nodes = await schedulePage([], { saved });
    assert.deepEqual(selectedMembers(nodes), ["demo-miri", "demo-snow"]);
  }
  const blocked = await schedulePage([], { saved: "[]", blockRead: true, blockWrite: true });
  assert.equal(blocked.get("#all-members").checked, true);
  checkOption(blocked, "#member-options", "demo-snow", false);
  assert.deepEqual(selectedMembers(blocked), ["demo-miri"]);
  const readOnly = await schedulePage([], { saved: '["demo-miri"]', blockWrite: true });
  checkOption(readOnly, "#member-options", "demo-snow", true);
  assert.equal(readOnly.get("#all-members").checked, true);
});

test("日期變更切至選擇日期並互斥高亮，今日回台灣當日，本週依所選日期", async () => {
  const events = [{ ...schedule.events[0], date: "2027-01-03" }];
  const nodes = await schedulePage(events);
  const pressed = () => ["#today-view", "#week-view", "#date-view"].map((id) => nodes.get(id).getAttribute("aria-pressed"));
  assert.deepEqual(pressed(), ["true", "false", "false"]);
  const date = nodes.get("#selected-date");
  date.value = "2027-01-03";
  date.dispatchEvent(new Event("change"));
  assert.deepEqual(pressed(), ["false", "false", "true"]);
  assert.equal(nodes.get("#range-title").textContent, "2027-01-03 行程");
  assert.equal(nodes.get("#message").textContent, "共 1 筆行程");
  nodes.get("#week-view").dispatchEvent(new Event("click"));
  assert.deepEqual(pressed(), ["false", "true", "false"]);
  assert.equal(nodes.get("#range-title").textContent, "2026-12-28 — 2027-01-03");
  assert.equal(nodes.get("#schedule").children.length, 7);
  nodes.get("#date-view").dispatchEvent(new Event("click"));
  assert.deepEqual(pressed(), ["false", "false", "true"]);
  assert.equal(nodes.get("#schedule").children.length, 1);
  nodes.get("#today-view").dispatchEvent(new Event("click"));
  assert.equal(date.value, taipeiDate());
  assert.deepEqual(pressed(), ["true", "false", "false"]);
});

test("事件狀態只提供六種匯入狀態，舊狀態不混入選項或符合結果", async () => {
  const events = ["scheduled", "changed", "live", "finished"].map((status) => ({ ...schedule.events[0], id: status, date: taipeiDate(), status }));
  const nodes = await schedulePage(events);
  assert.deepEqual(inputs(nodes, "#status-options").map((input) => input.value), ["scheduled", "tbd", "day_off", "unknown", "cancelled", "postponed"]);
  assert.equal(nodes.get("#message").textContent, "共 1 筆行程");
  assert.equal(selectEvents({ events }, members, taipeiDate(), "today").length, 4);
});

test("分開呈現未知、待定、休息、取消及延期的時間與狀態", async () => {
  const events = [["unknown", null], ["tbd", null], ["day_off", null], ["scheduled", "20:00"],
    ["cancelled", null], ["postponed", null]]
    .map(([status, time]) => ({ ...schedule.events[0], id: status, date: taipeiDate(), status, time, platform: null }));
  const nodes = await schedulePage(events);
  assert.equal(nodes.get("#message").textContent, "共 6 筆行程");
  const cards = nodes.get("#schedule").children[0].children.slice(1);
  assert.deepEqual(cards.map((card) => [card.children[0].textContent,
    card.children[1].children[2].children[0].textContent]), [
    ["20:00", "正常"], ["已取消", "已取消"], ["全天", "休息"], ["延期", "延期"],
    ["時間待定", "待定"], ["未知", "未知"],
  ]);
});

test("保留原開台時間並在卡片及篩選顯示已取消和延期", async () => {
  const cases = [
    { status: "cancelled", time: "18:00", label: "已取消" },
    { status: "postponed", time: "20:00", label: "延期" },
  ];
  const date = taipeiDate();
  const events = cases.map(({ status, time }) => ({ ...schedule.events[0], id: status, date, status, time }));
  const nodes = await schedulePage(events);
  const cards = nodes.get("#schedule").children[0].children.slice(1);
  const options = nodes.get("#status-options").children;
  assert.equal(cards.length, cases.length);
  for (const [index, { status, time, label }] of cases.entries()) {
    const card = cards[index];
    assert.equal(card.className, `event-card status-${status}`);
    assert.equal(card.children[0].textContent, time);
    assert.equal(card.children[1].children[2].children[0].textContent, label);
    const option = options.find(({ children: [input] }) => input.value === status);
    assert.ok(option);
    assert.equal(option.children[1].textContent, label);
  }
});

test("取消勾選即時隱藏行程，全不勾選顯示提示，重新勾選可恢復", async () => {
  const events = ["scheduled", "unknown"].map((status) => ({
    ...schedule.events[0], id: status, date: taipeiDate(), status,
  }));
  const nodes = await schedulePage(events);
  const inputs = nodes.get("#status-options").children.map((label) => label.children[0]);
  const unknown = inputs.find((input) => input.value === "unknown");
  assert.ok(unknown, "應提供未知狀態的核取方塊");
  assert.equal(nodes.get("#message").textContent, "共 2 筆行程");
  unknown.checked = false;
  nodes.get("#status-filters").dispatchEvent(new Event("change"));
  assert.equal(nodes.get("#message").textContent, "共 1 筆行程");
  assert.equal(nodes.get("#schedule").children[0].children[1].className, "event-card status-scheduled");
  inputs.forEach((input) => { input.checked = false; });
  nodes.get("#status-filters").dispatchEvent(new Event("change"));
  assert.match(nodes.get("#message").textContent, /請.*勾選.*事件狀態/);
  assert.equal(nodes.get("#schedule").children[0].children.length, 2);
  assert.equal(nodes.get("#schedule").children[0].children[1].className, "empty-day");
  unknown.checked = true;
  nodes.get("#status-filters").dispatchEvent(new Event("change"));
  assert.equal(nodes.get("#message").textContent, "共 1 筆行程");
  assert.equal(nodes.get("#schedule").children[0].children[1].className, "event-card status-unknown");
  nodes.get("#week-view").dispatchEvent(new Event("click"));
  assert.equal(nodes.get("#message").textContent, "共 1 筆行程");
  assert.equal(nodes.get("#schedule").children.length, 7);
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
