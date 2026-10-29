"use strict";

(() => {
  const root = document.documentElement;
  const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
  let preference = null;
  let toggle;
  try {
    const saved = localStorage.getItem("meridian-theme");
    if (saved === "light" || saved === "dark") preference = saved;
  } catch {
    // 偏好儲存遭封鎖時，仍可在本次瀏覽切換色系。
  }

  function renderTheme() {
    const dark = preference ? preference === "dark" : systemTheme.matches;
    root.dataset.theme = dark ? "dark" : "light";
    if (toggle) toggle.checked = dark;
  }

  renderTheme();
  systemTheme.addEventListener("change", () => {
    if (!preference) renderTheme();
  });

  document.addEventListener("DOMContentLoaded", () => {
    toggle = document.querySelector("#theme-toggle");
    renderTheme();
    toggle.addEventListener("change", () => {
      preference = toggle.checked ? "dark" : "light";
      renderTheme();
      try {
        localStorage.setItem("meridian-theme", preference);
      } catch {
        // 無法持久儲存時，保留本次瀏覽的手動選擇。
      }
    });
  }, { once: true });
})();
