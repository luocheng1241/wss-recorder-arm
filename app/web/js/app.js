const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

let pollTimer = null;
let liveId = null;
let remainingSec = 0;

async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  if (res.status === 401) {
    showLogin();
    throw new Error("unauthorized");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
  return data;
}

function showLogin() {
  $("#login-view").classList.remove("hidden");
  $("#app-view").classList.add("hidden");
  if (pollTimer) clearInterval(pollTimer);
}

function showApp() {
  $("#login-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  startPolling();
  loadSettings();
  loadWebDAV();
  refreshLibrary();
}

function fmtBytes(n) {
  if (!n) return "0 MB";
  return (n / 1024 / 1024).toFixed(2) + " MB";
}

function fmtRemain(sec) {
  if (sec == null) return "—";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  return `${h}h ${m}m ${s}s`;
}

function ticketClass(state) {
  if (state === "VALID") return "ok";
  if (state === "EXPIRING") return "warn";
  if (["EXPIRED", "NEEDS_INPUT", "EMPTY"].includes(state)) return "err";
  return "";
}

function setBadge(state) {
  const el = $("#rec-badge");
  el.textContent = state;
  el.className = "badge " + (state === "running" ? "ok" : state === "needs_ticket" ? "err" : "warn");
}

async function refreshStatus() {
  try {
    const st = await api("/api/status");
    const rec = st.recorder || {};
    const ticket = st.ticket || {};
    setBadge(rec.state || "—");
    $("#d-rec-state").textContent = rec.state || "—";
    $("#d-device").textContent = st.device_id || "—";
    $("#d-frames").textContent = rec.frame_count ?? 0;
    $("#d-bytes").textContent = fmtBytes(rec.total_bytes);
    $("#d-seg").textContent = rec.segment_index ?? 0;
    $("#d-uptime").textContent = (rec.uptime_sec || 0) + "s";
    $("#d-ticket-state").textContent = ticket.state || "—";
    $("#d-ticket-preview").textContent = ticket.preview || "—";
    remainingSec = ticket.remaining_sec ?? 0;
    $("#d-ticket-remain").textContent = fmtRemain(remainingSec);
    $("#d-convert").textContent = (st.convert_queue && st.convert_queue.pending) || 0;
    $("#d-disk").textContent = fmtBytes(st.disk && st.disk.recordings_bytes);
    $("#d-ffmpeg").textContent = st.ffmpeg ? "OK" : "missing";
    if (st.cleanup && st.cleanup.usage_mb != null) {
      const el = $("#cl-usage");
      if (el) {
        const maxMb = (st.cleanup.max_bytes || 0) / 1024 / 1024;
        el.textContent = `${st.cleanup.usage_mb} MB / ${maxMb.toFixed(0)} MB`;
      }
    }

    const need =
      ticket.state === "NEEDS_INPUT" ||
      ticket.state === "EXPIRED" ||
      ticket.state === "EMPTY" ||
      rec.state === "needs_ticket";
    const banner = $("#banner");
    if (need) {
      banner.classList.remove("hidden");
      banner.textContent = "Ticket 无效或已过期，请到 Ticket 页重新输入。";
    } else {
      banner.classList.add("hidden");
    }
  } catch (e) {
    /* login handled */
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  refreshStatus();
  pollTimer = setInterval(() => {
    remainingSec = Math.max(0, remainingSec - 1);
    $("#d-ticket-remain").textContent = fmtRemain(remainingSec);
    if (remainingSec % 5 === 0) refreshStatus();
    if ($("#tab-live").classList.contains("active")) refreshLive(false);
  }, 1000);
}

// Tabs
$$(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab").forEach((b) => b.classList.remove("active"));
    $$(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`#tab-${btn.dataset.tab}`).classList.add("active");
    if (btn.dataset.tab === "library") refreshLibrary();
    if (btn.dataset.tab === "live") refreshLive(true);
    if (btn.dataset.tab === "settings") {
      loadSettings();
      loadWebDAV();
    }
  });
});

// Auth
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#login-error").textContent = "";
  try {
    await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ password: $("#login-password").value }),
    });
    showApp();
  } catch (err) {
    $("#login-error").textContent = "密码错误";
  }
});

$("#btn-logout").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" });
  showLogin();
});

// Recorder
$("#btn-start").addEventListener("click", async () => {
  const r = await api("/api/recorder/start", { method: "POST" });
  if (!r.ok) alert(r.error || "启动失败，请检查 ticket");
  refreshStatus();
});
$("#btn-stop").addEventListener("click", async () => {
  await api("/api/recorder/stop", { method: "POST" });
  refreshStatus();
});

function extractTicket(raw) {
  const s = (raw || "").trim();
  if (!s) return "";
  // full wss url: ...?ticket=xxx or &ticket=xxx
  const m = s.match(/[?&]ticket=([^&\s#]+)/i);
  if (m) return decodeURIComponent(m[1]);
  // pasted "ticket=xxx"
  const m2 = s.match(/^ticket=(.+)$/i);
  if (m2) return decodeURIComponent(m2[1].trim());
  return s;
}

// Ticket
$("#btn-save-ticket").addEventListener("click", async () => {
  const ticket = extractTicket($("#ticket-input").value);
  if (!ticket) {
    alert("请粘贴 ticket，或完整的 wss://...?ticket=xxx 地址");
    return;
  }
  try {
    await api("/api/ticket", { method: "POST", body: JSON.stringify({ ticket }) });
    $("#ticket-msg").textContent = "已保存: " + ticket.slice(0, 8) + "...";
    $("#ticket-input").value = "";
    refreshStatus();
  } catch (e) {
    alert("保存失败: " + e.message);
  }
});
$("#btn-clear-ticket").addEventListener("click", async () => {
  await api("/api/ticket", { method: "DELETE" });
  $("#ticket-msg").textContent = "已清空";
  refreshStatus();
});
$("#btn-refresh-ticket").addEventListener("click", async () => {
  const r = await api("/api/ticket/refresh", { method: "POST" });
  $("#ticket-msg").textContent = r.ok ? "自动续票成功" : (r.error || "续票失败");
  refreshStatus();
});
$("#btn-import-cache").addEventListener("click", async () => {
  const raw = ($("#token-cache-input").value || "").trim();
  if (!raw) {
    alert("请粘贴 token_cache.json 全文，或只粘贴 ticket 字符串");
    return;
  }
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (e) {
    // allow bare ticket / wss url when user confuses the two boxes
    const t = extractTicket(raw);
    if (t && !raw.startsWith("{") && !raw.startsWith("[")) {
      try {
        await api("/api/ticket", { method: "POST", body: JSON.stringify({ ticket: t }) });
        $("#ticket-msg").textContent = "已按 ticket 保存（非 JSON）";
        $("#token-cache-input").value = "";
        refreshStatus();
        return;
      } catch (err) {
        alert("保存失败: " + err.message);
        return;
      }
    }
    alert(
      "JSON 无效: " + e.message +
      "\n\n请粘贴完整的 token_cache.json（以 { 开头、以 } 结束）。\n" +
      "若只是 ticket，请用上方「Ticket」输入框，不要用导入区。"
    );
    return;
  }
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    alert("JSON 必须是对象，例如 {\"token\":\"...\",\"cookies\":{...}}");
    return;
  }
  try {
    await api("/api/ticket/token-cache", { method: "POST", body: JSON.stringify(payload) });
    $("#ticket-msg").textContent = "token_cache 已导入";
    refreshStatus();
  } catch (e) {
    alert("导入失败: " + e.message);
  }
});

// Live (WebDAV)
async function refreshLive(force) {
  try {
    const r = await api("/api/preview/latest");
    const item = r.item;
    if (!item) {
      $("#live-meta").textContent = r.error === "webdav_not_configured"
        ? "请先在 Settings 配置 WebDAV"
        : "WebDAV 上暂无视频（请等待同步）";
      return;
    }
    const path = item.rel_path_mp4 || item.rel_path || item.id;
    $("#live-meta").textContent = `${path} (${fmtBytes(item.bytes_mp4 || item.size)})`;
    if (force || path !== liveId) {
      liveId = path;
      const v = $("#live-video");
      v.src = `/api/recordings/file?path=${encodeURIComponent(path)}`;
      v.play().catch(() => {});
    }
  } catch (e) {
    $("#live-meta").textContent = "加载失败: " + (e.message || e);
  }
}
$("#btn-live-refresh").addEventListener("click", () => refreshLive(true));

// Library (WebDAV)
async function refreshLibrary() {
  const day = $("#lib-day").value;
  const qs = new URLSearchParams({ limit: "200", refresh: "true" });
  if (day) qs.set("date", day);
  let list, days;
  try {
    [list, days] = await Promise.all([
      api("/api/recordings?" + qs.toString()),
      api("/api/recordings/days"),
    ]);
  } catch (e) {
    $("#lib-body").innerHTML = `<tr><td colspan="4">加载失败: ${e.message}</td></tr>`;
    return;
  }
  if (list.error === "webdav_not_configured") {
    $("#lib-body").innerHTML = `<tr><td colspan="4">请先在 Settings 配置 WebDAV</td></tr>`;
    return;
  }
  const sel = $("#lib-day");
  const cur = sel.value;
  sel.innerHTML = '<option value="">全部日期</option>';
  (days.days || []).forEach((d) => {
    const o = document.createElement("option");
    o.value = d.date;
    o.textContent = `${d.date} (${d.count})`;
    if (d.date === cur) o.selected = true;
    sel.appendChild(o);
  });
  const body = $("#lib-body");
  body.innerHTML = "";
  (list.items || []).forEach((it) => {
    const path = it.rel_path_mp4 || it.rel_path || it.id;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${path || "—"}</td>
      <td>${fmtBytes(it.bytes_mp4 || it.size)}</td>
      <td>${it.modified || "—"}</td>
      <td></td>`;
    const td = tr.lastElementChild;
    const play = document.createElement("button");
    play.textContent = "播放";
    play.onclick = () => {
      const v = $("#lib-video");
      v.classList.remove("hidden");
      v.src = `/api/recordings/file?path=${encodeURIComponent(path)}`;
      v.play().catch(() => {});
    };
    const dl = document.createElement("button");
    dl.textContent = "打开";
    dl.onclick = () => {
      window.open(`/api/recordings/file?path=${encodeURIComponent(path)}`, "_blank");
    };
    td.append(play, dl);
    body.appendChild(tr);
  });
  if (!(list.items || []).length) {
    body.innerHTML = `<tr><td colspan="4">暂无远端录像</td></tr>`;
  }
}
$("#btn-lib-refresh").addEventListener("click", refreshLibrary);
$("#lib-day").addEventListener("change", refreshLibrary);

// Settings
async function loadSettings() {
  const s = await api("/api/settings");
  $("#set-segment").value = s.segment_duration;
  $("#set-device").value = s.device_id;
  $("#set-relay").value = s.relay_url;
  $("#set-keep-raw").checked = !!s.keep_raw;
  $("#cl-enabled").checked = !!s.cleanup_enabled;
  $("#cl-after-sync").checked = !!s.delete_after_sync;
  $("#cl-max-gb").value = s.cleanup_max_gb ?? 20;
  loadCleanupStatus();
}
$("#btn-save-settings").addEventListener("click", async () => {
  await api("/api/settings", {
    method: "PUT",
    body: JSON.stringify({
      segment_duration: Number($("#set-segment").value),
      device_id: $("#set-device").value,
      relay_url: $("#set-relay").value,
      keep_raw: $("#set-keep-raw").checked,
    }),
  });
  alert("设置已保存（录制中重启后生效）");
});

async function loadCleanupStatus() {
  try {
    const st = await api("/api/cleanup/status");
    const maxMb = (st.max_bytes || 0) / 1024 / 1024;
    $("#cl-usage").textContent = `${st.usage_mb ?? 0} MB / ${maxMb.toFixed(0)} MB`;
    if (st.last_run) {
      const q = st.last_run.quota || {};
      const s = st.last_run.synced_cleanup || {};
      $("#cl-status").textContent =
        `上次: 同步后删 ${s.deleted ?? 0} · 配额删 ${q.deleted ?? 0} · ${st.last_run.finished_at || ""}`;
    }
  } catch (e) {}
}
$("#btn-save-cleanup").addEventListener("click", async () => {
  await api("/api/cleanup/config", {
    method: "PUT",
    body: JSON.stringify({
      enabled: $("#cl-enabled").checked,
      delete_after_sync: $("#cl-after-sync").checked,
      max_gb: Number($("#cl-max-gb").value),
    }),
  });
  $("#cl-status").textContent = "清理设置已保存";
  loadCleanupStatus();
});
$("#btn-cleanup-now").addEventListener("click", async () => {
  $("#cl-status").textContent = "清理中...";
  const r = await api("/api/cleanup/run-now", { method: "POST" });
  $("#cl-status").textContent = JSON.stringify(r);
  loadCleanupStatus();
  refreshLibrary();
  refreshStatus();
});

async function loadWebDAV() {
  const c = await api("/api/webdav/config");
  $("#wd-enabled").checked = !!c.enabled;
  $("#wd-url").value = c.url || "";
  $("#wd-user").value = c.username || "";
  $("#wd-base").value = c.remote_base || "";
  $("#wd-cron").value = c.cron || "";
  const st = await api("/api/webdav/status");
  $("#wd-status").textContent = st.last_run
    ? `上次: ok=${st.last_run.ok_count} fail=${st.last_run.fail_count} pending=${st.pending}`
    : `pending=${st.pending ?? 0}`;
}
$("#btn-save-webdav").addEventListener("click", async () => {
  const body = {
    enabled: $("#wd-enabled").checked,
    url: $("#wd-url").value,
    username: $("#wd-user").value,
    remote_base: $("#wd-base").value,
    cron: $("#wd-cron").value,
  };
  const pass = $("#wd-pass").value;
  if (pass) body.password = pass;
  await api("/api/webdav/config", { method: "PUT", body: JSON.stringify(body) });
  $("#wd-pass").value = "";
  loadWebDAV();
});
$("#btn-sync-now").addEventListener("click", async () => {
  $("#wd-status").textContent = "同步中...";
  const r = await api("/api/webdav/sync-now", { method: "POST" });
  $("#wd-status").textContent = JSON.stringify(r);
  refreshLibrary();
});

// boot
(async () => {
  try {
    await api("/api/auth/me");
    showApp();
  } catch {
    showLogin();
  }
})();
