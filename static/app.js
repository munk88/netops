/* netops-mvp 控制台前端逻辑 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const chatInput = $("chat-input");
  const chatMessages = $("chat-messages");
  const trace = $("trace");
  const devicesEl = $("devices");
  const reportEl = $("report");
  const reportLink = $("report-link");
  const modal = $("confirm-modal");
  const connBadge = $("conn-badge");
  const modeBadge = $("mode-badge");

  let es = null;
  let pendingCid = null;

  // ---------- 通用 ----------
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function setConn(state) {
    connBadge.className = "badge " + (state === "online" ? "badge-ok" : "badge-neutral");
    connBadge.textContent = state === "online" ? "● 已连接" : "● 未连接";
  }

  async function fetchStatus() {
    try {
      const r = await fetch("/api/status");
      const s = await r.json();
      modeBadge.textContent = s.llm_mode === "llm"
        ? "模式：大模型 " + s.model
        : "模式：规则引擎（无 API Key）";
      setConn("online");
    } catch (e) { setConn("offline"); }
  }

  // ---------- 对话 ----------
  function addMsg(role, text) {
    const m = el("div", "msg " + role, text);
    chatMessages.appendChild(m);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  // ---------- 执行轨迹 ----------
  const PERM = {
    read: { cls: "read", badge: "只读·自主", bcls: "badge-read" },
    test: { cls: "tool", badge: "测试·需确认", bcls: "badge-test" },
    change: { cls: "tool", badge: "变更·需审批", bcls: "badge-change" },
  };

  function permOf(note) {
    if (/变更|审批/i.test(note)) return PERM.change;
    if (/确认/i.test(note)) return PERM.test;
    return PERM.read;
  }

  function renderStep(data) {
    if (data.kind === "final") {
      const box = el("div", "step-final");
      box.appendChild(el("div", "final-label", "✓ 最终回答"));
      box.appendChild(el("div", null, data.content || ""));
      trace.appendChild(box);
      return;
    }
    if (data.kind === "blocked") {
      const box = el("div", "step blocked");
      const row = el("div", "step-row");
      row.appendChild(el("span", "step-tool", "⛔ " + data.tool));
      box.appendChild(row);
      box.appendChild(el("div", "step-note", "被拦截：" + (data.note || "权限不足")));
      trace.appendChild(box);
      return;
    }
    if (data.kind === "tool") {
      const p = permOf(data.note);
      const box = el("div", "step " + p.cls);
      const row = el("div", "step-row");
      row.appendChild(el("span", "step-tool", data.tool));
      const badge = el("span", "badge " + p.bcls, p.badge);
      row.appendChild(badge);
      box.appendChild(row);
      if (data.args && Object.keys(data.args).length) {
        box.appendChild(el("div", "step-args", JSON.stringify(data.args)));
      }
      if (data.observation) {
        const t = el("div", "obs-toggle", "▸ 查看观察结果");
        const obs = el("div", "obs", data.observation);
        t.addEventListener("click", () => {
          obs.classList.toggle("open");
          t.textContent = obs.classList.contains("open") ? "▾ 收起观察结果" : "▸ 查看观察结果";
        });
        box.appendChild(t);
        box.appendChild(obs);
      }
      trace.appendChild(box);
      return;
    }
    if (data.kind === "error") {
      const box = el("div", "step blocked");
      box.appendChild(el("div", "step-row", "⚠ " + (data.content || "执行出错")));
      trace.appendChild(box);
    }
  }

  function traceStatus(text) {
    const box = el("div", "trace-status");
    box.appendChild(el("span", "spinner"));
    box.appendChild(el("span", null, text));
    trace.appendChild(box);
    return box;
  }

  // ---------- 流式接收 ----------
  function connectStream() {
    if (es) es.close();
    es = new EventSource("/api/stream");
    es.onmessage = (e) => {
      let ev;
      try { ev = JSON.parse(e.data); } catch (_) { return; }
      handleEvent(ev);
    };
    es.onerror = () => { /* 流结束或网络问题，EventSource 会尝试重连；done 后由我们主动 close */ };
  }

  function handleEvent(ev) {
    switch (ev.type) {
      case "status":
        traceStatus(ev.text);
        break;
      case "step":
        renderStep(ev.data);
        trace.scrollTop = trace.scrollHeight;
        break;
      case "final":
        addMsg("agent", ev.text);
        break;
      case "report_ready":
        loadReport();
        break;
      case "confirm_required":
        pendingCid = ev.cid;
        const badge = $("confirm-level-badge");
        badge.className = "badge " + (/审批/i.test(ev.level) || ev.level === "change" ? "badge-change" : "badge-test");
        badge.textContent = ev.level === "change" ? "变更·需审批" : "测试·需确认";
        $("confirm-title").textContent = ev.title;
        modal.style.display = "flex";
        break;
      case "error":
        traceStatus("出错：" + ev.text);
        addMsg("agent", "⚠ " + ev.text);
        break;
      case "done":
        if (es) { es.close(); es = null; }
        setButtons(true);
        fetchStatus();
        break;
    }
  }

  // ---------- 提交指令 ----------
  async function send(message) {
    const text = (message || chatInput.value).trim();
    if (!text) return;
    setButtons(false);
    addMsg("user", text);
    chatInput.value = "";
    trace.innerHTML = "";
    trace.appendChild(el("div", "trace-empty", ""));
    trace.lastChild.remove();
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        addMsg("agent", "⚠ " + (err.detail || "发送失败"));
        setButtons(true);
        return;
      }
      connectStream();
    } catch (e) {
      addMsg("agent", "⚠ 无法连接服务：" + e.message);
      setButtons(true);
    }
  }

  function setButtons(enable) {
    $("btn-send").disabled = !enable;
    $("btn-quick").disabled = !enable;
  }

  // ---------- 确认 ----------
  async function decide(decision) {
    if (pendingCid == null) return;
    const cid = pendingCid;
    pendingCid = null;
    modal.style.display = "none";
    await fetch("/api/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cid, decision }),
    });
  }

  // ---------- 设备仪表盘 ----------
  async function loadDevices() {
    try {
      const r = await fetch("/api/devices");
      const data = await r.json();
      devicesEl.innerHTML = "";
      for (const name of Object.keys(data)) {
        devicesEl.appendChild(deviceCard(name, data[name]));
      }
      $("device-ts").textContent = new Date().toLocaleTimeString();
    } catch (_) { /* 服务未就绪时静默 */ }
  }

  function deviceCard(name, d) {
    const card = el("div", "device-card");
    const top = el("div", "device-top");
    top.appendChild(el("div", "device-name", name));
    const vendor = el("div", "device-vendor", (d.vendor || "") + " · " + (d.model || ""));
    top.appendChild(vendor);
    card.appendChild(top);

    const meta = el("div", "device-meta");
    const st = String(d.status || "").toLowerCase();
    const statusDot = st === "up" ? "ok" : (st === "degraded" ? "warn" : "down");
    meta.appendChild(kpi("状态", '<span class="dot ' + statusDot + '"></span>' + (d.status || "-"), true));
    meta.appendChild(kpi("CPU", (d.cpu ?? "-") + "%"));
    meta.appendChild(kpi("内存", (d.mem ?? "-") + "%"));
    card.appendChild(meta);

    // 接口：兼容 dict {name: status} 与数组 [{name,status,ip}]
    let ifaces = [];
    if (Array.isArray(d.interfaces)) {
      ifaces = d.interfaces;
    } else if (d.interfaces && typeof d.interfaces === "object") {
      ifaces = Object.keys(d.interfaces).map((k) => ({
        name: k, status: d.interfaces[k], ip: d.ip_map && d.ip_map[k] || "",
      }));
    }
    if (ifaces.length) {
      const ifs = el("div", "device-ifaces");
      ifaces.forEach((itf) => {
        const col = String(itf.status).toLowerCase() === "up" ? "#2e9e5b" : "#c0392b";
        ifs.appendChild(el("div", null,
          itf.name + "  " + (itf.ip || "-") + "  <span style='color:" + col + "'>● " + itf.status + "</span>"));
      });
      card.appendChild(ifs);
    }
    return card;
  }

  function kpi(label, value, isHtml) {
    const d = el("div");
    d.appendChild(el("div", null, label));
    const b = el("b");
    if (isHtml) b.innerHTML = value; else b.textContent = value;
    d.appendChild(b);
    return d;
  }

  // ---------- 报告 ----------
  async function loadReport() {
    try {
      const r = await fetch("/api/report");
      const data = await r.json();
      if (data.markdown) {
        reportEl.textContent = data.markdown;
        if (data.html_path) {
          reportLink.style.display = "";
          reportLink.href = "/report-html";
        }
      }
    } catch (_) { }
  }

  // ---------- 事件绑定 ----------
  $("btn-send").addEventListener("click", () => send());
  chatInput.addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
  $("btn-clear").addEventListener("click", () => {
    chatMessages.innerHTML = "";
    trace.innerHTML = '<div class="trace-empty">运行一条指令后，这里会实时展示 Agent 的每一步动作。</div>';
  });
  $("btn-quick").addEventListener("click", () => send("全网巡检并生成报告"));
  document.querySelectorAll(".chip").forEach((c) => {
    c.addEventListener("click", () => send(c.dataset.msg));
  });
  $("btn-approve").addEventListener("click", () => decide(true));
  $("btn-reject").addEventListener("click", () => decide(false));

  // ---------- 初始化 ----------
  fetchStatus();
  loadDevices();
  loadReport();
  setInterval(loadDevices, 3000);
})();
