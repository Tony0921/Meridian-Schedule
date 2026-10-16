"use strict";

const STATUS_LABELS = Object.freeze({
  scheduled: "正常", changed: "已異動", cancelled: "已取消", postponed: "延期",
  live: "直播中", finished: "已結束", day_off: "休息", working_day: "工作日", tbd: "待定",
});

function taipeiDate(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(now);
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function weekDates(selectedDate) {
  const start = new Date(`${selectedDate}T00:00:00Z`);
  if (Number.isNaN(start.getTime())) throw new Error("日期格式不正確");
  start.setUTCDate(start.getUTCDate() - (start.getUTCDay() + 6) % 7);
  return Array.from({ length: 7 }, (_, offset) => {
    const day = new Date(start);
    day.setUTCDate(day.getUTCDate() + offset);
    return day.toISOString().slice(0, 10);
  });
}

function selectEvents(schedule, members, selectedDate, view, memberId = "") {
  const dates = new Set(view === "week" ? weekDates(selectedDate) : [selectedDate]);
  const enabled = new Set(members.filter((member) => member.enabled).map((member) => member.id));
  return schedule.events.filter((event) => dates.has(event.date) && enabled.has(event.member_id)
    && (!memberId || event.member_id === memberId))
    .sort((a, b) => a.date.localeCompare(b.date) || (a.time || "99:99").localeCompare(b.time || "99:99")
      || a.id.localeCompare(b.id));
}

function safeUrl(value) {
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

async function startApp() {
  const dateInput = document.querySelector("#selected-date");
  const memberSelect = document.querySelector("#member");
  const container = document.querySelector("#schedule");
  const message = document.querySelector("#message");
  const todayButton = document.querySelector("#today-view");
  const weekButton = document.querySelector("#week-view");
  let view = "today";
  dateInput.value = taipeiDate();

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function addLink(parent, label, value) {
    const url = safeUrl(value);
    if (!url) return;
    const link = element("a", label);
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    parent.append(link);
  }

  try {
    const [members, schedule] = await Promise.all(["members", "schedule"].map(async (name) => {
      const response = await fetch(`./data/${name}.json`, { cache: "no-store" });
      if (!response.ok) throw new Error(`無法讀取 ${name}`);
      return response.json();
    }));
    const memberMap = new Map(members.map((member) => [member.id, member]));
    for (const member of members.filter((item) => item.enabled)) {
      const option = element("option", member.name);
      option.value = member.id;
      memberSelect.append(option);
    }
    document.querySelector("#updated-at").textContent = schedule.updated_at
      ? `最後更新 ${new Intl.DateTimeFormat("zh-TW", { timeZone: "Asia/Taipei", dateStyle: "short", timeStyle: "short" }).format(new Date(schedule.updated_at))}`
      : "尚無更新資料";

    function render() {
      if (!dateInput.value || !dateInput.validity.valid) return;
      const selectedDate = dateInput.value;
      const dates = view === "week" ? weekDates(selectedDate) : [selectedDate];
      const events = selectEvents(schedule, members, selectedDate, view, memberSelect.value);
      todayButton.setAttribute("aria-pressed", String(view === "today"));
      weekButton.setAttribute("aria-pressed", String(view === "week"));
      document.querySelector("#range-title").textContent = view === "week"
        ? `${dates[0]} — ${dates[6]}` : `${selectedDate} 行程`;
      container.replaceChildren();
      message.textContent = events.length ? `共 ${events.length} 筆行程` : "這段時間還沒有行程，換個日期看看吧。";
      for (const date of dates) {
        const group = element("section", undefined, "day-group");
        const label = new Intl.DateTimeFormat("zh-TW", {
          timeZone: "UTC", month: "numeric", day: "numeric", weekday: "long",
        }).format(new Date(`${date}T00:00:00Z`));
        group.append(element("h3", label));
        const daily = events.filter((event) => event.date === date);
        if (!daily.length) group.append(element("p", "尚無行程", "empty-day"));
        for (const event of daily) {
          const card = element("article", undefined, `event-card status-${event.status}`);
          card.append(element("p", event.time || (event.status === "day_off" ? "全天" : "時間待定"), "event-time"));
          const body = element("div", undefined, "event-body");
          body.append(element("p", memberMap.get(event.member_id).name, "member-name"));
          body.append(element("h4", event.title));
          const metadata = element("div", undefined, "metadata");
          metadata.append(element("span", STATUS_LABELS[event.status] || event.status, "badge"));
          if (event.origin === "sudden_stream") metadata.append(element("span", "突發", "badge sudden"));
          if (event.platform) metadata.append(element("span", { youtube: "YouTube", twitch: "Twitch", other: "其他" }[event.platform]));
          body.append(metadata);
          const links = element("div", undefined, "event-links");
          addLink(links, "前往直播 ↗", event.url);
          const member = memberMap.get(event.member_id);
          if (member.x_username && !event.source_post_id.startsWith("demo-")) {
            addLink(links, "來源貼文 ↗", `https://x.com/${encodeURIComponent(member.x_username)}/status/${encodeURIComponent(event.source_post_id)}`);
          } else {
            links.append(element("span", `來源：${event.source_post_id}`));
          }
          body.append(links);
          card.append(body);
          group.append(card);
        }
        container.append(group);
      }
    }

    dateInput.addEventListener("change", render);
    memberSelect.addEventListener("change", render);
    todayButton.addEventListener("click", () => { view = "today"; render(); });
    weekButton.addEventListener("click", () => { view = "week"; render(); });
    render();
  } catch {
    container.replaceChildren();
    message.textContent = "行程載入失敗，請稍後重新整理。若在本機預覽，請先建置網站並使用 HTTP 伺服器開啟。";
    message.setAttribute("role", "alert");
  }
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { taipeiDate, weekDates, selectEvents, safeUrl };
}
if (typeof document !== "undefined") startApp();
