"use strict";
/* EE Solutions · Quotes — front end. No third-party code, no secrets, nothing sensitive in URLs. */
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const API = window.API_BASE || "";
const SYM = {NGN:"₦",USD:"$",EUR:"€",GBP:"£",ZAR:"R ",GHS:"GH₵",KES:"KSh ",CAD:"CA$",AED:"AED "};
const WEAK = new Set(["NGN","GHS","KES","ZAR"]);              // rates are quoted as "1 STRONG = x WEAK"
let TOKEN = sessionStorage.getItem("tk"), ME = null, META = null, SET = {}, RES = null;
let lastSaved = null, dirty = false, termsTouched = false, formReady = false, calcTimer = 0, calcSeq = 0, blobUrl = null, blobName = "quote.pdf", HIST = [], AUDIT = [];

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const nf = (n, d = 2) => Number(n || 0).toLocaleString("en-US", {minimumFractionDigits: d, maximumFractionDigits: d});
const unitFmt = n => Number(n || 0).toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 4});
const money = (n, c) => (SYM[c] || "") + nf(n);
const num = v => { const x = parseFloat(v); return Number.isFinite(x) ? x : 0; };
const safeName = s => String(s || "quote").replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 60);
const todayLagos = () => new Date().toLocaleDateString("en-CA", {timeZone: "Africa/Lagos"});

function toast(msg, type = "ok", ms = 4200) {
  const t = document.createElement("div"); t.className = "toast " + type; t.setAttribute("role", type === "err" ? "alert" : "status");
  t.innerHTML = `<svg class="i"><use href="#${type === "err" ? "i-alert" : "i-check"}"/></svg><span>${esc(msg)}</span>`;
  $("#toasts").appendChild(t); setTimeout(() => t.remove(), ms);
}
function busy(btn, on, label) {
  btn.disabled = on; const sp = btn.querySelector(".spin"); if (sp) sp.classList.toggle("hide", !on);
  if (label) { const l = btn.querySelector(".lbl"); if (l) l.textContent = label; }
}

/* ---------- API ---------- */
async function api(path, opt = {}) {
  const h = {...(opt.headers || {})}; if (TOKEN) h.Authorization = "Bearer " + TOKEN;
  if (opt.json !== undefined) { h["Content-Type"] = "application/json"; opt = {...opt, body: JSON.stringify(opt.json)}; }
  let r; try { r = await fetch(API + path, {...opt, headers: h}); } catch { throw Error("Cannot reach the server. Check your connection."); }
  if (r.status === 401 && path !== "/api/auth/login") { logout("Please sign in again."); throw Error("Session expired"); }
  if (!r.ok) {
    let m = r.statusText;
    try { const j = await r.json(); m = typeof j.detail === "string" ? j.detail : (j.detail || []).map(d => `${(d.loc || []).slice(-1)[0] || "field"}: ${d.msg}`).join("; "); } catch {}
    throw Error(m || "Something went wrong");
  }
  return r;
}
const J = async (p, o) => (await api(p, o)).json();

/* ---------- sign in ---------- */
let needCode = false;
$("#pwtog").onclick = () => { const p = $("#lpass"), show = p.type === "password"; p.type = show ? "text" : "password"; $("#pwtog use").setAttribute("href", show ? "#i-eyeoff" : "#i-eye"); };
$("#lpass").addEventListener("keyup", e => $("#caps").classList.toggle("hide", !(e.getModifierState && e.getModifierState("CapsLock"))));
$("#loginForm").addEventListener("submit", async e => {
  e.preventDefault(); const err = $("#lerr"); err.classList.add("hide");
  const email = $("#lemail").value.trim(), pw = $("#lpass").value;
  if (!email || !pw) { err.textContent = "Enter your email and password."; err.classList.remove("hide"); return; }
  busy($("#lbtn"), true);
  try {
    const r = await J("/api/auth/login", {method: "POST", json: {email, password: pw, code: needCode ? $("#lcode").value : ""}});
    if (r.mfa_required) { needCode = true; $("#loginStep1").classList.add("hide"); $("#loginStep2").classList.remove("hide"); $("#loginHint").textContent = "Two-step sign-in is on for your account."; $("#lbtn .lbl").textContent = "Verify"; $("#lcode").focus(); return; }
    TOKEN = r.token; sessionStorage.setItem("tk", TOKEN); $("#lpass").value = ""; $("#lcode").value = ""; needCode = false; await boot();
  } catch (ex) { err.textContent = ex.message; err.classList.remove("hide"); }
  finally { busy($("#lbtn"), false); }
});
function resetLogin() {
  needCode = false; $("#loginStep1").classList.remove("hide"); $("#loginStep2").classList.add("hide"); $("#lcode").value = ""; $("#lpass").value = "";
  $("#loginHint").textContent = "Sign in with your EE Solutions account."; $("#lbtn .lbl").textContent = "Sign in";
}
function logout(msg) {
  TOKEN = null; sessionStorage.removeItem("tk"); ME = null; META = null; formReady = false; dirty = false; lastSaved = null;
  closeModal(); $("#rows").innerHTML = ""; $$("#t-new input:not([type=checkbox]):not([type=range]), #t-new textarea").forEach(i => i.value = "");
  $("#app").classList.add("hide"); $("#login").classList.remove("hide"); resetLogin();
  if (msg) { $("#lerr").textContent = msg; $("#lerr").classList.remove("hide"); }
}
$("#signout").onclick = () => logout();

/* ---------- boot ---------- */
async function boot() {
  if (!TOKEN) return;
  try { ME = await J("/api/auth/me"); } catch { return; }
  const admin = ["admin", "superadmin"].includes(ME.role);
  $("#whoEmail").textContent = ME.email; $("#whoRole").textContent = ME.role === "superadmin" ? "super admin" : ME.role; $("#avatar").textContent = ME.email[0];
  $("#admtab").classList.toggle("hide", !admin);
  $("#login").classList.add("hide"); $("#app").classList.remove("hide");
  try { [META, SET] = await Promise.all([J("/api/meta"), J("/api/settings")]); } catch (e) { toast(e.message, "err"); return; }
  if (!formReady) await initForm();
  renderTfa(); showTab("new"); recalc();
}
function showTab(t) {
  $$("#nav button").forEach(b => b.classList.toggle("on", b.dataset.t === t));
  ["new", "hist", "adm", "acc"].forEach(x => $("#t-" + x).classList.toggle("hide", x !== t));
  $("#mbar").style.display = t === "new" ? "" : "none";
  if (t === "hist") loadHist(); if (t === "adm") { loadUsers(); loadAudit(); } window.scrollTo({top: 0});
}
$$("#nav button").forEach(b => b.onclick = () => showTab(b.dataset.t));

/* ---------- form setup ---------- */
async function initForm() {
  formReady = true;
  const opts = META.currencies.map(c => `<option value="${c.code}">${c.code} · ${esc(c.name)}</option>`).join("");
  $("#src").innerHTML = opts; $("#out").innerHTML = opts;
  const saved = JSON.parse(localStorage.getItem("ee_cur") || "{}");
  $("#src").value = saved.src || "USD"; $("#out").value = saved.out || "NGN";
  $("#vat").value = +(num(SET.vat_rate) * 100).toFixed(2); setMargin(num(SET.margin) * 100);
  const prep = JSON.parse(localStorage.getItem("ee_prep") || "null") || {name: META.prepared.name, role: META.prepared.role, email: META.prepared.email, phone: META.prepared.phone};
  $("#pname").value = prep.name || ""; $("#prole").value = prep.role || ""; $("#pmail").value = prep.email || ""; $("#pphone").value = prep.phone || "";
  $("#auth").value = META.authorized_by || ""; $("#qdate").value = todayLagos();
  applyInternal();
  fillTerms(true); addRow(); updateCurLabels(); await applyRateDefault(true); newRef(); loadDist(); titlePrev(); renderChecks();
  dirty = false;
}
async function newRef() { try { $("#ref").value = (await J("/api/quotes/next-number")).reference; } catch {} }
async function loadDist() { try { $("#distlist").innerHTML = (await J("/api/distributors")).map(d => `<option value="${esc(d)}">`).join(""); } catch {} }
$("#newref").onclick = newRef;

/* ---------- currencies & exchange rate ---------- */
function orient(src, out) {
  if (src === out) return {same: true, base: src, quote: out, invert: false};
  if (WEAK.has(src) && !WEAK.has(out)) return {base: out, quote: src, invert: true};
  return {base: src, quote: out, invert: false};
}
const pair = () => orient($("#src").value, $("#out").value);
function fxValue() { const o = pair(); if (o.same) return 1; const h = num($("#fx").value); return !h ? 0 : (o.invert ? 1 / h : h); }
function updateCurLabels() {
  const src = $("#src").value, out = $("#out").value, o = pair();
  $$(".cur-src").forEach(e => e.textContent = src); $$(".cur-out").forEach(e => e.textContent = out);
  $("#fxBox").classList.toggle("hide", o.same); $("#fxPre").textContent = `1 ${o.base} =`; $("#fxSuf").textContent = o.quote;
  $("#budgetL").textContent = `Customer budget in ${src} (optional)`;
}
async function applyRateDefault(first) {
  const o = pair(); if (o.same) return; $("#fxHint").textContent = "";
  const key = `fx_${o.base}_${o.quote}`, saved = SET[key] || (o.base === "USD" && o.quote === "NGN" ? SET.fx_rate : null);
  if (saved) $("#fx").value = saved; else if (!first || !$("#fx").value) $("#fx").value = "";
  try {
    const r = await J(`/api/fx/live?base=${o.base}&quote=${o.quote}`);
    if (r.rate) {
      const live = +(r.rate >= 100 ? r.rate.toFixed(2) : r.rate.toPrecision(5));
      if (!saved) $("#fx").value = live;
      $("#fxHint").innerHTML = `Market today ≈ <b>${nf(live, live < 10 ? 4 : 2)}</b> · <a href="#" id="usefx">use it</a>${saved ? " · your saved rate is shown" : ""}`;
      $("#usefx").onclick = e => { e.preventDefault(); $("#fx").value = live; recalc(); };
    } else if (!saved) $("#fxHint").textContent = "Live rate unavailable. Please type the rate.";
  } catch { if (!saved) $("#fxHint").textContent = "Live rate unavailable. Please type the rate."; }
  recalc();
}
function curChanged() {
  localStorage.setItem("ee_cur", JSON.stringify({src: $("#src").value, out: $("#out").value}));
  updateCurLabels(); applyRateDefault(false); dirty = true;
}
$("#src").onchange = $("#out").onchange = curChanged;

/* ---------- margin / terms / title ---------- */
function setMargin(v) { v = Math.max(0, Math.min(95, num(v))); $("#marginNum").value = +v.toFixed(4); $("#marginRange").value = Math.min(v, 80); $$("#marginChips button").forEach(b => b.classList.toggle("on", +b.dataset.m === v)); }
$("#marginRange").oninput = e => { setMargin(e.target.value); recalc(); };
$("#marginNum").oninput = e => { const v = num(e.target.value); $("#marginRange").value = Math.min(v, 80); $$("#marginChips button").forEach(b => b.classList.toggle("on", +b.dataset.m === v)); recalc(); };
$$("#marginChips button").forEach(b => b.onclick = () => { setMargin(b.dataset.m); recalc(); });
function fillTerms(force) {
  if (!force && termsTouched) return; const vat = +(num($("#vat").value)).toFixed(2);
  $("#terms").value = META.terms_template.map(t => t.replace("{vat}", String(vat)).replace("{days}", META.valid_days)).join("\n"); termsTouched = false;
}
$("#terms").oninput = () => termsTouched = true; $("#resetTerms").onclick = () => fillTerms(true);
$("#vat").oninput = () => { fillTerms(false); recalc(); };
function titlePrev() { const t = (($("#product").value || "SOFTWARE").trim().toUpperCase()) + " QUOTE"; $("#titlePrev").textContent = t; $("#sumTitle").textContent = t; }
$("#product").oninput = () => { titlePrev(); }; $("#company").oninput = () => { $("#sumClient").textContent = $("#company").value.trim() || "No client yet"; $("#company").classList.remove("bad"); renderChecks(); };
$("#fx").oninput = recalc;

/* ---------- lines ---------- */
function addRow(it = {}) {
  const tr = document.createElement("tr"), v = x => esc(x ?? "");
  tr.innerHTML = `<td><input class="sku" value="${v(it.sku)}" aria-label="SKU"></td>
  <td><textarea class="desc" rows="1" aria-label="Description">${v(it.description)}</textarea></td>
  <td><input class="dur" value="${v(it.duration)}" placeholder="12 months" aria-label="Duration"></td>
  <td><input class="qty" type="number" step="any" min="0" value="${it.qty ?? 1}" aria-label="Quantity"></td>
  <td><input class="list" type="number" step="any" min="0" value="${it.list_unit ?? ""}" placeholder="0.00" aria-label="Distributor price per unit"></td>
  <td class="adv"><input class="disc" type="number" step="0.1" min="0" value="${it.discount ? +(it.discount * 100).toFixed(2) : 0}" aria-label="Distributor discount %"></td>
  <td><input class="lm" type="number" step="0.1" min="0" placeholder="default" title="Leave empty to use the default margin" value="${it.margin != null ? +(it.margin * 100).toFixed(2) : ""}" aria-label="Line margin %"></td>
  <td class="r st">–</td>
  <td><button type="button" class="icon-btn danger" title="Remove line" aria-label="Remove line"><svg class="i"><use href="#i-trash"/></svg></button></td>`;
  tr.querySelectorAll("input,textarea").forEach(i => i.addEventListener("input", () => { if (i.classList.contains("desc")) grow(i); recalc(); }));
  tr.querySelector("button").onclick = () => { tr.remove(); if (!$("#rows").children.length) addRow(); recalc(); };
  $("#rows").appendChild(tr); grow(tr.querySelector(".desc"));
}
const grow = t => { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 160) + "px"; };
$("#addrow").onclick = () => { addRow(); $("#rows").lastElementChild.querySelector(".sku").focus(); };
$("#addps").onclick = () => { addRow({sku: "PS", description: "Professional Services, Local Support and Quarterly Health Check", qty: 1}); $("#rows").lastElementChild.querySelector(".list").focus(); };
$("#advtog").onchange = e => document.body.classList.toggle("show-adv", e.target.checked);
function items() {
  return $$("#rows tr").map(tr => { const g = c => tr.querySelector(c).value;
    return {sku: g(".sku").trim(), description: g(".desc").trim(), duration: g(".dur").trim(), qty: num(g(".qty")) || 0.0001, list_unit: num(g(".list")),
            discount: num(g(".disc")) / 100, margin: g(".lm") === "" ? null : num(g(".lm")) / 100}; });
}
const calcPayload = () => ({items: items(), margin: num($("#marginNum").value) / 100, fx_rate: fxValue() || 1, vat_rate: num($("#vat").value) / 100});

/* ---------- live calculation ---------- */
function recalc() { dirty = true; clearTimeout(calcTimer); calcTimer = setTimeout(doCalc, 180); }
async function doCalc() {
  if (!TOKEN || !formReady) return; const my = ++calcSeq, out = $("#out").value, src = $("#src").value;
  try {
    const r = await J("/api/calc", {method: "POST", json: calcPayload()}); if (my !== calcSeq) return; RES = r;
    $$("#rows tr").forEach((tr, i) => { const l = r.lines[i]; if (!l) return; tr.querySelector(".st").innerHTML = `<b>${nf(l.sell_total_out)}</b><small>${out === "NGN" ? nf(l.sell_unit_out) : unitFmt(l.sell_unit_out)} / unit</small>`; });
    $("#sumTotal").textContent = nf(r.total_out); $("#sumCur").textContent = out; $("#mTotal").textContent = money(r.total_out, out);
    $("#sumNet").textContent = money(r.subtotal_out, out); $("#sumVat").textContent = money(r.vat_out, out); $("#sumVatL").textContent = `VAT (${+num($("#vat").value).toFixed(2)}%)`;
    $("#sumSrcRow").classList.toggle("hide", src === out); $("#sumSrc").textContent = money(r.total_src, src);
    $("#intCost").textContent = money(r.cost_total, src); $("#intProfit").textContent = money(r.profit_src, src);
    $("#intMargin").textContent = (r.margin * 100).toFixed(2) + "%"; $("#meter").style.width = Math.max(0, Math.min(100, r.margin * 200)) + "%";
    $("#smsg").textContent = ""; 
  } catch (e) { if (my === calcSeq) $("#smsg").textContent = e.message; }
  renderChecks();
}
const CHECKS = [
  {id: "line", ok: "At least one line has a price", bad: "Add at least one line with a price", test: () => items().some(i => i.list_unit > 0)},
  {id: "fx", ok: "Exchange rate entered", bad: "Enter the exchange rate", test: () => pair().same || fxValue() > 0, only: () => !pair().same},
  {id: "co", ok: "Company name entered", bad: "Enter the company name", test: () => !!$("#company").value.trim()},
  {id: "by", ok: "Prepared-by name entered", bad: "Enter who prepared the quote", test: () => !!$("#pname").value.trim()},
  {id: "ref", ok: "Reference entered", bad: "Enter a reference", test: () => !!$("#ref").value.trim()},
];
const problems = () => CHECKS.filter(c => !c.test()).map(c => c.bad);
function renderChecks() {
  $("#checks").innerHTML = CHECKS.filter(c => !c.only || c.only()).map(c => { const ok = c.test();
    return `<li class="${ok ? "ok" : ""}"><svg class="i"><use href="#i-check"/></svg>${esc(ok ? c.ok : c.bad)}</li>`; }).join("");
}
["pname", "ref"].forEach(id => $("#" + id).addEventListener("input", renderChecks));

/* ---------- internal numbers toggle ---------- */
function applyInternal() { const off = localStorage.getItem("ee_int") === "0"; document.querySelector(".internal").classList.toggle("off", off); $("#intTog use").setAttribute("href", off ? "#i-eyeoff" : "#i-eye"); }
$("#intTog").onclick = () => { localStorage.setItem("ee_int", localStorage.getItem("ee_int") === "0" ? "1" : "0"); applyInternal(); };

/* ---------- distributor PDF ---------- */
const drop = $("#drop");
["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", e => { const f = e.dataTransfer.files[0]; if (f) readPdf(f); });
drop.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#pdf").click(); } });
$("#pdf").onchange = e => { const f = e.target.files[0]; if (f) readPdf(f); e.target.value = ""; };
function detectCurrency(t) {
  const c = {USD: (t.match(/US\$|USD|\$/g) || []).length, NGN: (t.match(/₦|NGN|NAIRA/gi) || []).length, EUR: (t.match(/€|EUR\b/g) || []).length, GBP: (t.match(/£|GBP/g) || []).length};
  const best = Object.entries(c).sort((a, b) => b[1] - a[1])[0]; return best[1] > 0 ? best[0] : null;
}
async function readPdf(f) {
  if (f.type !== "application/pdf" && !/\.pdf$/i.test(f.name)) return toast("Please choose a PDF file.", "err");
  if (f.size > 15e6) return toast("That PDF is larger than 15 MB.", "err");
  drop.classList.remove("done"); $("#dropBar").classList.remove("hide"); $("#dropT").textContent = "Reading " + f.name + "…";
  const fd = new FormData(); fd.append("file", f);
  try {
    const r = await J("/api/pdf/parse", {method: "POST", body: fd});
    if (!r.has_text_layer) { $("#dropT").textContent = "This PDF is a scan"; $("#dropS").textContent = "No text could be read. Please type the lines in by hand."; return; }
    if (!r.items.length) { $("#dropT").textContent = "No lines recognised"; $("#dropS").textContent = "Add the lines by hand and send this PDF to Peter so the reader can learn this layout."; return; }
    $("#rows").innerHTML = ""; r.items.forEach(i => addRow({...i, duration: "12 months"}));
    const cur = detectCurrency(r.text || ""); if (cur && META.currencies.some(c => c.code === cur) && cur !== $("#src").value) { $("#src").value = cur; curChanged(); toast(`Prices look like ${cur}. Distributor currency set to ${cur}. Please confirm.`, "ok", 6000); }
    drop.classList.add("done"); $("#dropT").textContent = `${r.items.length} line${r.items.length > 1 ? "s" : ""} read from ${f.name}`; $("#dropS").textContent = "Please check them against the original PDF. Click to replace the file."; recalc();
  } catch (e) { $("#dropT").textContent = "Could not read that PDF"; $("#dropS").textContent = e.message; }
  finally { $("#dropBar").classList.add("hide"); }
}

/* ---------- defaults, budget ---------- */
$("#savedef").onclick = async () => {
  try { const o = pair(), b = {margin: num($("#marginNum").value) / 100, vat_rate: num($("#vat").value) / 100};
    if (!o.same && num($("#fx").value) > 0) { b.fx_pair = `${o.base}_${o.quote}`; b.fx_value = num($("#fx").value); }
    SET = await J("/api/settings", {method: "PUT", json: b}); toast("Saved as the default for everyone."); } catch (e) { toast(e.message, "err"); }
};
$("#fit").onclick = async () => {
  try { const r = await J("/api/calc/budget", {method: "POST", json: {items: items(), budget: num($("#budget").value)}}); setMargin(r.margin * 100); recalc(); toast(`Margin set to ${(r.margin * 100).toFixed(2)}% to match the budget.`); }
  catch (e) { toast(e.message, "err"); }
};

/* ---------- save, preview, download ---------- */
function quoteBody() {
  return {...calcPayload(), reference: $("#ref").value.trim(), distributor: $("#dist").value.trim(), source_currency: $("#src").value, quote_currency: $("#out").value,
    quote_date: $("#qdate").value, product_title: $("#product").value.trim(), company_name: $("#company").value.trim(), client_name: $("#client").value.trim(),
    position: $("#position").value.trim(), address1: $("#addr1").value.trim(), address2: $("#addr2").value.trim(), city_country: $("#city").value.trim(),
    prepared_by: $("#pname").value.trim(), prepared_role: $("#prole").value.trim(), prepared_email: $("#pmail").value.trim(), prepared_phone: $("#pphone").value.trim(),
    authorized_by: $("#auth").value.trim(), terms: $("#terms").value.trim()};
}
async function ensureSaved() {
  const p = problems(); if (p.length) { if (!$("#company").value.trim()) $("#company").classList.add("bad"); toast(p[0] + ".", "err"); throw Error("incomplete"); }
  const body = quoteBody(), key = JSON.stringify(body);
  if (lastSaved && lastSaved.key === key) return lastSaved;
  const r = lastSaved ? await J("/api/quotes/" + lastSaved.id, {method: "PUT", json: body}) : await J("/api/quotes", {method: "POST", json: body});
  lastSaved = {key, id: r.id, ref: r.reference}; dirty = false; loadDist();
  if ($("#remember").checked) localStorage.setItem("ee_prep", JSON.stringify({name: body.prepared_by, role: body.prepared_role, email: body.prepared_email, phone: body.prepared_phone}));
  toast(`Saved as ${r.reference}`); return lastSaved;
}
async function pdfBlob(id) { const r = await api(`/api/quotes/${id}/pdf`); return await r.blob(); }
function saveBlob(blob, name) { const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000); }
async function doDownload(btns) {
  btns.forEach(b => busy(b, true));
  try { const s = await ensureSaved(); const blob = await pdfBlob(s.id); saveBlob(blob, safeName(s.ref) + ".pdf"); toast("Quote downloaded.");
    $("#smsg").textContent = `Saved as ${s.ref}. You can find it again under “Saved quotes”.`; }
  catch (e) { if (e.message !== "incomplete") toast(e.message, "err"); }
  finally { btns.forEach(b => busy(b, false)); }
}
$("#dl").onclick = () => doDownload([$("#dl")]); $("#dl2").onclick = () => doDownload([$("#dl2")]); $("#dl3").onclick = () => doDownload([$("#dl3")]);
$("#prev").onclick = async () => { try { const s = await ensureSaved(); openPreview(await pdfBlob(s.id), safeName(s.ref) + ".pdf"); } catch (e) { if (e.message !== "incomplete") toast(e.message, "err"); } };
function openPreview(blob, name) { closeModal(); blobUrl = URL.createObjectURL(blob); blobName = name; window._blob = blob; $("#pdfFrame").src = blobUrl; $("#modal").classList.remove("hide"); $("#mx").focus(); }
function closeModal() { $("#modal").classList.add("hide"); $("#pdfFrame").removeAttribute("src"); if (blobUrl) URL.revokeObjectURL(blobUrl); blobUrl = null; window._blob = null; }
$("#mx").onclick = closeModal; $("#modal").addEventListener("click", e => { if (e.target.id === "modal") closeModal(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });
$("#mtab").onclick = () => { if (blobUrl) window.open(blobUrl, "_blank", "noopener"); };
$("#mdl").onclick = () => { if (window._blob) saveBlob(window._blob, blobName); };
$("#newq").onclick = async () => {
  if (dirty && !confirm("Start a new quote? Anything not yet downloaded will be cleared.")) return; resetQuote();
};
async function resetQuote() {
  $("#rows").innerHTML = ""; addRow(); ["dist", "product", "company", "client", "position", "addr1", "addr2", "city", "budget"].forEach(id => $("#" + id).value = "");
  $("#qdate").value = todayLagos(); lastSaved = null; fillTerms(true); setMargin(num(SET.margin) * 100); $("#vat").value = +(num(SET.vat_rate) * 100).toFixed(2);
  drop.classList.remove("done"); $("#dropT").textContent = "Drop the distributor's PDF here"; $("#dropS").textContent = "or click to choose a file · we read the SKUs, quantities and prices for you";
  $("#smsg").textContent = ""; titlePrev(); $("#sumClient").textContent = "No client yet"; await newRef(); await applyRateDefault(false); dirty = false; window.scrollTo({top: 0, behavior: "smooth"});
}
window.addEventListener("beforeunload", e => { if (TOKEN && dirty && ($("#company")?.value || "").trim()) { e.preventDefault(); e.returnValue = ""; } });

/* ---------- steps indicator ---------- */
const stepEls = $$("#steps li");
stepEls.forEach(li => li.onclick = () => document.getElementById(li.dataset.s).scrollIntoView({behavior: "smooth", block: "start"}));
if ("IntersectionObserver" in window) {
  const ids = ["s1", "s2", "s3", "s4"], seen = new Map();
  const io = new IntersectionObserver(es => { es.forEach(e => seen.set(e.target.id, e.intersectionRatio)); const top = ids.find(id => (seen.get(id) || 0) > 0.25) || ids[0], idx = ids.indexOf(top);
    stepEls.forEach((li, i) => { li.classList.toggle("on", i === idx); li.classList.toggle("done", i < idx); }); }, {threshold: [0, .25, .5, 1]});
  ids.forEach(id => io.observe(document.getElementById(id)));
}

/* ---------- saved quotes ---------- */
async function loadHist() { try { HIST = await J("/api/quotes"); renderHist(); } catch (e) { toast(e.message, "err"); } }
function renderHist() {
  const q = $("#hsearch").value.trim().toLowerCase(), rows = HIST.filter(x => !q || [x.reference, x.company, x.distributor, x.created_by].join(" ").toLowerCase().includes(q)), admin = ["admin", "superadmin"].includes(ME?.role);
  $("#hempty").classList.toggle("hide", rows.length > 0); $("#htable").classList.toggle("hide", !rows.length);
  $("#hrows").innerHTML = rows.map(x => `<tr data-id="${x.id}"><td><b>${esc(x.reference)}</b></td><td>${esc(x.date)}</td><td>${esc(x.company)}</td><td>${esc(x.distributor)}</td>
    <td class="r"><b>${money(x.total_out, x.quote_currency)}</b> <span class="badge">${esc(x.quote_currency)}</span></td><td class="mut">${esc(x.created_by)}</td>
    <td><div class="cell-actions"><button class="icon-btn" data-a="prev" title="Preview" aria-label="Preview"><svg class="i"><use href="#i-eye"/></svg></button>
    <button class="icon-btn" data-a="dl" title="Download" aria-label="Download"><svg class="i"><use href="#i-download"/></svg></button>
    <button class="icon-btn" data-a="reuse" title="Reuse as a new quote" aria-label="Reuse"><svg class="i"><use href="#i-reuse"/></svg></button>
    ${admin ? `<button class="icon-btn danger" data-a="del" title="Delete" aria-label="Delete"><svg class="i"><use href="#i-trash"/></svg></button>` : ""}</div></td></tr>`).join("");
}
$("#hsearch").oninput = renderHist;
$("#hrows").addEventListener("click", async e => {
  const b = e.target.closest("button"); if (!b) return; const id = +b.closest("tr").dataset.id, x = HIST.find(h => h.id === id);
  try {
    if (b.dataset.a === "dl") saveBlob(await pdfBlob(id), safeName(x.reference) + ".pdf");
    if (b.dataset.a === "prev") openPreview(await pdfBlob(id), safeName(x.reference) + ".pdf");
    if (b.dataset.a === "reuse") await reuse(id);
    if (b.dataset.a === "del" && confirm(`Delete ${x.reference}? This cannot be undone.`)) { await J("/api/quotes/" + id, {method: "DELETE"}); loadHist(); toast("Quote deleted."); }
  } catch (err) { toast(err.message, "err"); }
});
async function reuse(id) {
  const q = await J("/api/quotes/" + id);
  $("#src").value = q.source_currency; $("#out").value = q.quote_currency; updateCurLabels(); localStorage.setItem("ee_cur", JSON.stringify({src: q.source_currency, out: q.quote_currency}));
  const o = pair(); $("#fx").value = o.same ? "" : +(o.invert ? 1 / q.fx_rate : q.fx_rate).toPrecision(8); $("#fxHint").textContent = "Rate copied from the old quote. Check it.";
  setMargin(q.margin * 100); $("#vat").value = +(q.vat_rate * 100).toFixed(2); $("#dist").value = q.distributor; $("#product").value = q.product_title; $("#company").value = q.company_name;
  $("#client").value = q.client_name; $("#position").value = q.position; $("#addr1").value = q.address1; $("#addr2").value = q.address2; $("#city").value = q.city_country;
  $("#pname").value = q.prepared_by; $("#prole").value = q.prepared_role; $("#pmail").value = q.prepared_email; $("#pphone").value = q.prepared_phone; $("#auth").value = q.authorized_by;
  $("#terms").value = q.terms; termsTouched = true; $("#qdate").value = todayLagos(); $("#rows").innerHTML = ""; q.items.forEach(addRow); lastSaved = null;
  await newRef(); titlePrev(); $("#sumClient").textContent = q.company_name; showTab("new"); await doCalc(); dirty = false; toast("Quote loaded with a new reference. Change anything you need.");
}

/* ---------- admin ---------- */
async function loadUsers() {
  try { const us = await J("/api/admin/users"), isSuper = ME.role === "superadmin";
    $("#urows").innerHTML = us.map(u => `<tr data-id="${u.id}"><td>${esc(u.email)}</td><td><span class="badge ${u.role !== "user" ? "blue" : ""}">${esc(u.role === "superadmin" ? "super admin" : u.role)}</span></td>
      <td>${u.locked ? '<span class="badge bad">locked</span>' : '<span class="badge ok">active</span>'}</td><td>${u.totp_enabled ? '<span class="badge ok">on</span>' : '<span class="badge">off</span>'}</td>
      <td><div class="cell-actions">${u.locked ? '<button class="btn sm primary" data-a="unlock">Unlock</button>' : ""}
      <button class="btn sm ghost" data-a="reset">Reset password</button>${u.totp_enabled ? '<button class="btn sm ghost" data-a="r2fa">Reset 2-step</button>' : ""}
      ${u.role === "superadmin" || (u.role === "admin" && !isSuper) ? "" : '<button class="icon-btn danger" data-a="del" title="Delete user" aria-label="Delete user"><svg class="i"><use href="#i-trash"/></svg></button>'}</div></td></tr>`).join("");
  } catch (e) { toast(e.message, "err"); }
}
$("#urows").addEventListener("click", async e => {
  const b = e.target.closest("button"); if (!b) return; const tr = b.closest("tr"), id = tr.dataset.id, email = tr.children[0].textContent;
  try {
    if (b.dataset.a === "unlock") await J(`/api/admin/users/${id}/unlock`, {method: "POST"});
    if (b.dataset.a === "reset") { const p = prompt(`New temporary password for ${email} (10+ characters, letters and numbers)`); if (!p) return; await J(`/api/admin/users/${id}/reset-password`, {method: "POST", json: {new_password: p}}); toast("Password reset."); }
    if (b.dataset.a === "r2fa") { if (!confirm(`Turn off two-step sign-in for ${email}?`)) return; await J(`/api/admin/users/${id}/reset-2fa`, {method: "POST"}); }
    if (b.dataset.a === "del") { if (!confirm(`Delete ${email}?`)) return; await J(`/api/admin/users/${id}`, {method: "DELETE"}); }
    loadUsers(); loadAudit();
  } catch (err) { toast(err.message, "err"); }
});
$("#nadd").onclick = async () => { $("#aerr").textContent = "";
  try { await J("/api/admin/users", {method: "POST", json: {email: $("#ne").value, password: $("#np").value, role: $("#nr").value}}); $("#ne").value = $("#np").value = ""; toast("User added."); loadUsers(); loadAudit(); }
  catch (e) { $("#aerr").textContent = e.message; } };
async function loadAudit() { try { AUDIT = await J("/api/admin/audit"); renderAudit(); } catch {} }
function renderAudit() {
  const q = $("#asearch").value.trim().toLowerCase(), bad = a => /failed|locked|unknown|bad_code/.test(a), good = a => /_ok/.test(a);
  $("#arows").innerHTML = AUDIT.filter(x => !q || [x.actor, x.action, x.detail].join(" ").toLowerCase().includes(q)).map(x =>
    `<tr><td class="mut" style="white-space:nowrap">${esc(new Date(x.ts + "Z").toLocaleString("en-GB", {timeZone: "Africa/Lagos", dateStyle: "short", timeStyle: "medium"}))}</td><td>${esc(x.actor)}</td>
     <td><span class="badge ${bad(x.action) ? "bad" : good(x.action) ? "ok" : ""}">${esc(x.action.replace(/_/g, " "))}</span></td><td>${esc(x.detail)}</td><td class="mut">${esc(x.ip)}</td></tr>`).join("");
}
$("#asearch").oninput = renderAudit;

/* ---------- account: password + two-step ---------- */
$("#cpw").onclick = async () => {
  try { const r = await J("/api/auth/change-password", {method: "POST", json: {old_password: $("#op").value, new_password: $("#npw").value}});
    TOKEN = r.token; sessionStorage.setItem("tk", TOKEN); $("#pwmsg").textContent = ""; $("#op").value = $("#npw").value = ""; toast("Password changed. Other sessions were signed out."); }
  catch (e) { $("#pwmsg").textContent = e.message; $("#pwmsg").className = "err-t"; }
};
function renderTfa() {
  const on = !!ME?.totp_enabled; $("#tfaBadge").textContent = on ? "on" : "off"; $("#tfaBadge").className = "badge " + (on ? "ok" : "");
  $("#tfaOff").classList.toggle("hide", on); $("#tfaOn").classList.toggle("hide", !on); $("#tfaSetup").classList.add("hide"); $("#tfaErr").textContent = "";
}
$("#tfaStart").onclick = async () => { try { const r = await J("/api/auth/2fa/setup", {method: "POST"}); $("#tfaKey").textContent = r.secret.match(/.{1,4}/g).join(" "); $("#tfaKey").dataset.k = r.secret;
  $("#tfaOff").classList.add("hide"); $("#tfaSetup").classList.remove("hide"); $("#tfaCode").focus(); } catch (e) { $("#tfaErr").textContent = e.message; } };
$("#tfaCopy").onclick = async () => { try { await navigator.clipboard.writeText($("#tfaKey").dataset.k); toast("Setup key copied."); } catch { toast("Select the key and copy it.", "err"); } };
$("#tfaEnable").onclick = async () => { try { await J("/api/auth/2fa/enable", {method: "POST", json: {code: $("#tfaCode").value}}); ME.totp_enabled = true; $("#tfaCode").value = ""; renderTfa(); toast("Two-step sign-in is on."); } catch (e) { $("#tfaErr").textContent = e.message; } };
$("#tfaOffBtn").onclick = async () => { try { await J("/api/auth/2fa/disable", {method: "POST", json: {password: $("#tfaPw").value, code: $("#tfaC2").value}}); ME.totp_enabled = false; $("#tfaPw").value = $("#tfaC2").value = ""; renderTfa(); toast("Two-step sign-in is off."); } catch (e) { $("#tfaErr").textContent = e.message; } };

/* ---------- sign out after 30 minutes of no activity ---------- */
let idleT; const bump = () => { clearTimeout(idleT); if (TOKEN) idleT = setTimeout(() => logout("Signed out after 30 minutes of inactivity."), 30 * 60 * 1000); };
["click", "keydown", "mousemove", "touchstart"].forEach(ev => document.addEventListener(ev, bump, {passive: true}));
$("#t-new").addEventListener("input", () => { dirty = true; });
boot().then(bump);
