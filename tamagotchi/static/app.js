const $ = (id) => document.getElementById(id);
let state = null;
let busy = false;

// 游戏时钟：与 game.py 一致，不操作时现实 1 秒 = 游戏 1 分钟。
const GAME_MINUTES_PER_SECOND = 1;
let fetchedAt = Date.now();

function elapsedGameMinutes() {
  return (Date.now() - fetchedAt) / 1000 * GAME_MINUTES_PER_SECOND;
}

function liveCooldown(minutes) {
  return Math.max(0, minutes - elapsedGameMinutes());
}

function clockText(minutes) {
  const total = Math.max(0, Math.floor(minutes));
  const day = Math.floor(total / 1440) + 1;
  const hour = Math.floor((total % 1440) / 60);
  const minute = total % 60;
  return "第 " + day + " 天 " + String(hour).padStart(2, "0") + ":" + String(minute).padStart(2, "0");
}

function periodText(hour) {
  if (hour < 5) return "凌晨";
  if (hour < 8) return "清晨";
  if (hour < 11) return "上午";
  if (hour < 13) return "中午";
  if (hour < 17) return "下午";
  if (hour < 19) return "傍晚";
  if (hour < 23) return "晚上";
  return "深夜";
}

function durationText(minutes) {
  const total = Math.max(0, Math.round(minutes));
  if (!total) return "现在";
  const days = Math.floor(total / 1440);
  const hours = Math.floor((total % 1440) / 60);
  const mins = total % 60;
  if (days) return days + " 天" + (hours ? hours + " 小时" : "");
  if (hours) return hours + " 小时" + (mins ? mins + " 分" : "");
  return mins + " 分钟";
}

function renderClock() {
  if (!state || !state.time) return;
  const minutes = state.time.minutes + elapsedGameMinutes();
  $("clockVal").textContent = clockText(minutes) + " · " + periodText(Math.floor(minutes % 1440 / 60));
  $("restBtn").disabled = busy || liveCooldown(state.rest_cooldown) > 0;
  refreshSheetCooldowns();
}

// 打工 / 娱乐面板上带冷却的按钮每秒只改倒计时文字；冷却一好就重渲染整块面板。
function refreshSheetCooldowns() {
  const sheet = $("sheet");
  const panel = sheet.dataset.panel;
  if (!state || sheet.hidden || (panel !== "work" && panel !== "play")) return;
  const list = panel === "work" ? state.jobs : state.activities;
  let expired = false;
  document.querySelectorAll("#sheetBody .act[data-cool]").forEach((btn) => {
    const entry = (list || []).find((x) => x.id === btn.dataset.cool);
    if (!entry) return;
    const left = liveCooldown(entry.cooldown);
    if (left > 0) { btn.textContent = durationText(left); return; }
    expired = true;
  });
  if (expired) renderSheet(panel);
}

async function api(path, body) {
  const options = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : undefined;
  let res;
  try {
    res = await fetch(path, options);
  } catch (err) {
    throw new Error("连不上服务，看看终端里 server.py 还活着没");
  }
  const data = await res.json().catch(() => null);
  if (!data || !data.ok) {
    throw new Error((data && data.error) || "请求失败 HTTP " + res.status);
  }
  return data;
}

function toast(text, bad) {
  const el = $("toast");
  el.textContent = text;
  el.className = "toast" + (bad ? " bad" : "");
  el.hidden = false;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => { el.hidden = true; }, 2600);
}

function scrollChat() {
  const chat = $("chat");
  chat.scrollTop = chat.scrollHeight;
}

function bubble(text, kind, deltaText) {
  const wrapper = document.createElement("div");
  wrapper.className = "msg " + kind;
  const p = document.createElement("span");
  p.textContent = text;
  wrapper.appendChild(p);
  if (deltaText) {
    const d = document.createElement("span");
    d.className = "delta";
    d.textContent = deltaText;
    wrapper.appendChild(d);
  }
  $("chat").appendChild(wrapper);
  scrollChat();
  return wrapper;
}

function narrate(text) { return bubble(text, "narrate"); }

function setBusy(flag) {
  busy = flag;
  $("sendBtn").disabled = flag;
  $("input").disabled = flag;
  document.querySelectorAll(".actions button").forEach((b) => { b.disabled = flag; });
  if (!$("sheet").hidden) renderSheet($("sheet").dataset.panel);
}

function renderState(next) {
  state = next;
  fetchedAt = Date.now();
  $("avatar").textContent = next.girl.slice(0, 1);
  $("girlName").textContent = next.girl;
  $("stageName").textContent = next.stage.name;
  $("affBar").style.width = (next.affinity / next.affinity_max * 100) + "%";
  $("affNum").textContent = next.affinity + " / " + next.affinity_max;
  $("moodVal").textContent = next.mood;
  $("staminaVal").textContent = next.stamina;
  $("coinVal").textContent = next.coins;
  $("levelVal").textContent = next.level;
  $("expVal").textContent = next.exp + "/" + next.exp_need;
  renderClock();
  if (!$("sheet").hidden) renderSheet($("sheet").dataset.panel);
}

function renderHistory(history) {
  $("chat").innerHTML = "";
  history.forEach((m) => {
    bubble(m.content, m.role === "user" ? "me" : "them");
  });
  scrollChat();
}

function humanDelta(affinity, mood) {
  const bits = [];
  if (affinity) bits.push((affinity > 0 ? "+" : "") + affinity + " 好感");
  if (mood) bits.push((mood > 0 ? "+" : "") + mood + " 心情");
  return bits.length ? "（" + bits.join("，") + "）" : "";
}

async function send() {
  const input = $("input");
  const text = input.value.trim();
  if (!text || busy) return;
  input.value = "";
  bubble(text, "me");
  const thinking = bubble("……", "them typing");
  setBusy(true);
  try {
    const data = await api("/api/chat", { text });
    thinking.remove();
    bubble(data.result.reply, "them", humanDelta(data.result.affinity_delta, data.result.mood_delta));
    if (data.result.memory_added) toast("她记下了： " + data.result.memory_added);
    renderState(data.state);
  } catch (err) {
    thinking.remove();
    toast(err.message, true);
  } finally {
    setBusy(false);
    input.focus();
  }
}

async function doGift(itemId) {
  if (busy) return;
  setBusy(true);
  try {
    const data = await api("/api/gift", { item_id: itemId });
    closeSheet();
    const item = state.shop.find((i) => i.id === itemId);
    narrate("你把「" + item.emoji + " " + item.name + "」递了过去。");
    bubble(data.result.reply, "them", humanDelta(data.result.affinity_delta, data.result.mood_delta));
    renderState(data.state);
  } catch (err) {
    toast(err.message, true);
  } finally {
    setBusy(false);
  }
}

async function doWork(jobId) {
  if (busy) return;
  setBusy(true);
  try {
    const job = (state.jobs || []).find((j) => j.id === jobId) || { name: "打工", hours: 0 };
    const data = await api("/api/work", { job_id: jobId });
    closeSheet();
    narrate("你去" + job.name + "了，忙了 " + job.hours + " 小时。");
    bubble(data.result.reply, "them");
    toast("赚到 " + data.result.earned + " 金币" + (data.result.mood_note ? "（" + data.result.mood_note + "）" : ""));
    renderState(data.state);
  } catch (err) {
    toast(err.message, true);
    renderState(state);
  } finally {
    setBusy(false);
  }
}

async function doRest() {
  if (busy || !state) return;
  const left = liveCooldown(state.rest_cooldown);
  if (left > 0) { toast("刚休息过，还要等 " + durationText(left) + "（游戏内）", true); return; }
  setBusy(true);
  try {
    const data = await api("/api/rest", {});
    bubble(data.result.reply, "them");
    toast("睡了一觉，体力恢复到 " + data.result.stamina);
    renderState(data.state);
  } catch (err) {
    toast(err.message, true);
  } finally {
    setBusy(false);
  }
}

async function doActivity(activityId) {
  if (busy || !state) return;
  const act = (state.activities || []).find((a) => a.id === activityId);
  if (!act) return;
  setBusy(true);
  try {
    const data = await api("/api/activity", { activity_id: activityId });
    closeSheet();
    narrate(act.duo
      ? "你带着她一起去了「" + act.name + "」，一待就是 " + act.hours + " 小时。"
      : "你一个人去「" + act.name + "」，花了 " + act.cost + " 金币。");
    bubble(data.result.reply, "them", humanDelta(data.result.affinity_delta, data.result.mood_delta));
    if (data.result.memory_added) toast("她记下了： " + data.result.memory_added);
    renderState(data.state);
  } catch (err) {
    toast(err.message, true);
    renderState(state);
  } finally {
    setBusy(false);
  }
}

function renderSheet(panel) {
  const sheet = $("sheet");
  sheet.dataset.panel = panel;
  const body = $("sheetBody");
  body.innerHTML = "";
  if (!state) return;

  if (panel === "gift") {
    $("sheetTitle").textContent = "礼物 · 现有 " + state.coins + " 金币";
    state.shop.forEach((item) => {
      const row = document.createElement("div");
      row.className = "item";
      const emoji = document.createElement("div");
      emoji.className = "emoji";
      emoji.textContent = item.emoji;
      const info = document.createElement("div");
      info.className = "info";
      const name = document.createElement("b");
      name.textContent = item.name;
      const desc = document.createElement("span");
      desc.textContent = item.desc + " · " + item.price + " 金币";
      info.append(name, desc);
      const btn = document.createElement("button");
      btn.className = "act" + (item.affordable ? " buy" : "");
      btn.textContent = item.affordable ? "送给她" : "金币不足";
      btn.disabled = !item.affordable;
      btn.onclick = () => doGift(item.id);
      row.append(emoji, info, btn);
      body.appendChild(row);
    });
  } else if (panel === "work") {
    $("sheetTitle").textContent = "打工 · Lv." + state.level + " · " + clockText(state.time.minutes + elapsedGameMinutes());
    state.jobs.forEach((job) => {
      const row = document.createElement("div");
      row.className = "item" + (job.locked ? " locked" : "");
      const emoji = document.createElement("div");
      emoji.className = "emoji";
      emoji.textContent = job.emoji;
      const info = document.createElement("div");
      info.className = "info";
      const name = document.createElement("b");
      name.textContent = job.name + " · " + job.coins[0] + "~" + job.coins[1] + " 金币";
      const desc = document.createElement("span");
      desc.textContent = job.desc + " · 耗时 " + job.hours + " 小时 · 耗体力 " + job.stamina
        + (job.window_text === "随时" ? "" : " · " + job.window_text);
      info.append(name, desc);
      const btn = document.createElement("button");
      btn.className = "act";
      if (job.locked) {
        btn.textContent = "Lv." + job.level_req;
        btn.disabled = true;
      } else if (!job.open) {
        btn.textContent = "不在时段";
        btn.disabled = true;
      } else if (liveCooldown(job.cooldown) > 0) {
        btn.textContent = durationText(liveCooldown(job.cooldown));
        btn.disabled = true;
        btn.dataset.cool = job.id;
      } else if (!job.enough_stamina) {
        btn.textContent = "体力不足";
        btn.disabled = true;
      } else {
        btn.textContent = "去干活";
        btn.classList.add("buy");
        btn.onclick = () => doWork(job.id);
      }
      row.append(emoji, info, btn);
      body.appendChild(row);
    });
  } else if (panel === "play") {
    $("sheetTitle").textContent = "娱乐 · 现有 " + state.coins + " 金币 · 双人需好感 " + state.duo_affinity_req;
    state.activities.forEach((act) => {
      const row = document.createElement("div");
      row.className = "item" + (act.locked || act.affinity_locked ? " locked" : "");
      const emoji = document.createElement("div");
      emoji.className = "emoji";
      emoji.textContent = act.emoji;
      const info = document.createElement("div");
      info.className = "info";
      const name = document.createElement("b");
      name.textContent = act.name + (act.duo ? " · 双人" : " · 单人")
        + " · " + (act.cost ? act.cost + " 金币" : "免费");
      const desc = document.createElement("span");
      desc.textContent = act.desc + " · 耗时 " + act.hours + " 小时 · 耗体力 " + act.stamina
        + (act.window_text === "随时" ? "" : " · " + act.window_text)
        + (act.duo ? " · 好感 +" + act.affinity : "");
      info.append(name, desc);
      const btn = document.createElement("button");
      btn.className = "act";
      if (act.locked) {
        btn.textContent = "Lv." + act.level_req;
        btn.disabled = true;
      } else if (act.affinity_locked) {
        btn.textContent = "好感 " + act.affinity_req;
        btn.disabled = true;
      } else if (!act.open) {
        btn.textContent = "不在时段";
        btn.disabled = true;
      } else if (liveCooldown(act.cooldown) > 0) {
        btn.textContent = durationText(liveCooldown(act.cooldown));
        btn.disabled = true;
        btn.dataset.cool = act.id;
      } else if (!act.affordable) {
        btn.textContent = "金币不足";
        btn.disabled = true;
      } else if (!act.enough_stamina) {
        btn.textContent = "体力不足";
        btn.disabled = true;
      } else {
        btn.textContent = act.duo ? "约她出门" : "去玩";
        btn.classList.add("buy");
        btn.onclick = () => doActivity(act.id);
      }
      row.append(emoji, info, btn);
      body.appendChild(row);
    });
  } else if (panel === "memo") {
    $("sheetTitle").textContent = "回忆";
    const memos = document.createElement("div");
    memos.className = "memo-block";
    memos.innerHTML = "<h3>她记得的事</h3>";
    const ul = document.createElement("ul");
    (state.memories || []).slice().reverse().forEach((m) => {
      const li = document.createElement("li");
      li.textContent = m.content;
      ul.appendChild(li);
    });
    if (!ul.children.length) {
      const li = document.createElement("li");
      li.textContent = "（还没有什么值得记住的事）";
      ul.appendChild(li);
    }
    memos.appendChild(ul);
    body.appendChild(memos);

    const events = document.createElement("div");
    events.className = "memo-block";
    events.innerHTML = "<h3>最近发生的事</h3>";
    const ul2 = document.createElement("ul");
    (state.events || []).slice().reverse().forEach((e) => {
      const li = document.createElement("li");
      const time = document.createElement("span");
      time.textContent = clockText(e.ts);
      li.append(time, document.createTextNode(e.text));
      ul2.appendChild(li);
    });
    events.appendChild(ul2);
    body.appendChild(events);
  }

  if (busy) body.querySelectorAll("button").forEach((b) => { b.disabled = true; });
}

function openSheet(panel) {
  $("sheet").hidden = false;
  renderSheet(panel);
}

function closeSheet() {
  $("sheet").hidden = true;
  $("sheet").dataset.panel = "";
}

async function reset() {
  if (!confirm("确定要重新开始吗？当前存档会被清空。")) return;
  setBusy(true);
  try {
    const data = await api("/api/reset", {});
    renderState(data.state);
    renderHistory(data.state.history);
    narrate("【新的故事】" + (data.state.events[data.state.events.length - 1] || {}).text);
  } catch (err) {
    toast(err.message, true);
  } finally {
    setBusy(false);
  }
}

function bind() {
  $("sendBtn").onclick = send;
  $("input").addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });
  $("restBtn").onclick = doRest;
  $("resetBtn").onclick = reset;
  $("sheetClose").onclick = closeSheet;
  $("sheet").addEventListener("click", (e) => { if (e.target === $("sheet")) closeSheet(); });
  document.querySelectorAll(".actions button[data-panel]").forEach((btn) => {
    btn.onclick = () => openSheet(btn.dataset.panel);
  });
  setInterval(renderClock, 1000);
  setInterval(async () => {
    if (busy) return;
    try {
      const data = await api("/api/state");
      renderState(data.state);
    } catch (err) { /* 静默重试 */ }
  }, 30000);
}

async function boot() {
  bind();
  try {
    const data = await api("/api/state");
    renderState(data.state);
    renderHistory(data.state.history);
    if (!data.state.history.length) {
      const intro = (data.state.events || []).slice(-1)[0];
      if (intro) narrate("【开场】" + intro.text);
    }
  } catch (err) {
    toast(err.message, true);
  }
}

boot();
