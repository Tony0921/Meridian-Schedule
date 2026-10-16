const test = require("node:test");
const assert = require("node:assert/strict");
const { taipeiDate, weekDates, selectEvents, safeUrl } = require("../site/app.js");
const members = require("../data/members.json");
const schedule = require("../data/schedule.json");

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
