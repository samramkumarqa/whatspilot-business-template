// DOM-level XSS regression test: loads a templates/*.html page in jsdom, feeds hostile payloads through stubbed API responses,
// and fails visibly if any payload becomes live markup/script.
//   cd security_tests && npm install jsdom && node xss_dom_test.js ../templates/dashboard.html dashboard.html
const {JSDOM, VirtualConsole} = require("jsdom");
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const page = process.argv[3];
// payloads that would execute if inserted unescaped
const P = [
  '<img src=x onerror="window.__xss=(window.__xss||[]).concat(\'img\')">',
  '<svg onload="window.__xss=(window.__xss||[]).concat(\'svg\')">',
  '"><script>window.__xss=(window.__xss||[]).concat("script")</script>',
  "'-window.__xss=(window.__xss||[]).concat('attr')-'",
  '[click](javascript:window.__xss=1)',
  '<a href="javascript:window.__xss=1">x</a>',
];
const evil = (i) => P[i % P.length];
const customers = P.map((p, i) => ({phone: "+1555000000" + i, name: p, message_count: 3, last_seen: "2026-10-01 10:00:00", unread_count: 1, last_message: p, lead_score: 50, status: "New", intent: p, buying_stage: p, sentiment: p, priority: "High", last_seen_days: 1, confidence: 50, ai_paused: false}));
const msgs = P.map((p, i) => ({role: i % 2 ? "assistant" : "user", content: p + " **bold** [l](javascript:window.__xss=1)", created_at: "2026-10-01 10:00:00", sender: i % 2 ? "ai" : "customer"}));
const rules = P.map((p, i) => ({id: i + 1, name: p, description: p, enabled: 1, trigger_type: "lead_score", condition_json: [{field: "lead_score", operator: ">", value: 1}], action_json: [{name: p, type: "create_reminder", params: {text: p, title: p, days: 1}}], conditions: [], actions: []}));
const reminders = P.map((p, i) => ({id: i + 1, customer_phone: "+1555000000" + i, reminder_text: p, due_date: "2026-10-01", status: "Pending", source_rule_id: null, source_rule_name: p}));
function respond(url) {
  const u = url.toString();
  const j = (o) => ({ok: true, status: 200, json: async () => o, text: async () => JSON.stringify(o)});
  if (u.includes("customer-details") || u.includes("customer-search")) return j({status: "success", customers, total: customers.length, has_more: false});
  if (u.includes("/conversation/")) return j({status: "success", conversation: msgs, messages: msgs, history: msgs});
  if (u.includes("automation/rules")) return j({status: "success", rules});
  if (u.includes("/reminders")) return j({status: "success", reminders, total: reminders.length, overdue_count: 1});
  if (u.includes("/lead/")) return j({status: "success", lead: {status: "New", notes: P[0], summary: P[1], ai_summary: P[2], next_action: P[3], intent: P[0], objection: P[1]}});
  if (u.includes("/customer-profile")) return j({status: "success", profile: customers[0]});
  return j({status: "success"});
}
const vc = new VirtualConsole();
const errs = []; vc.on("jsdomError", e => errs.push(String(e.message).slice(0, 100)));
const dom = new JSDOM(html, {runScripts: "dangerously", pretendToBeVisual: true, url: "http://localhost:8000/" + page, virtualConsole: vc,
  beforeParse(w) {
    w.fetch = async (u) => respond(u);
    w.alert = () => {}; w.confirm = () => true;
    w.matchMedia = w.matchMedia || (() => ({matches: false, addListener() {}, removeListener() {}, addEventListener() {}}));
    w.scrollTo = () => {}; w.Element.prototype.scrollTo = () => {}; w.HTMLElement.prototype.scrollTo = () => {}; w.Element.prototype.scrollIntoView = () => {};
    w.Chart = function () { return {destroy() {}, update() {}}; };
    w.IntersectionObserver = w.ResizeObserver = function () { return {observe() {}, disconnect() {}, unobserve() {}}; };
    w.setInterval = () => 0;
  }});
const w = dom.window;
setTimeout(async () => {
  const d = w.document;
  const uid = d.getElementById("userId"); if (uid) uid.value = "+14155238886";
  const calls = ["loadCustomers", "loadAutomationRules", "loadAllReminders", "loadReminderBadge", "loadOpportunities"];
  for (const fn of calls) { try { if (typeof w[fn] === "function") await w[fn](); } catch (e) { errs.push(fn + ": " + String(e.message).slice(0, 80)); } }
  // open a conversation + customer panels for the first hostile customer
  for (const fn of [["editRule", 1], ["editRule", 2], ["editRule", 3], ["editRule", 4], ["selectCustomer", customers[0]], ["selectCustomer", customers[0].phone], ["loadConversation", customers[0].phone], ["loadLead", customers[0].phone]]) {
    try { if (typeof w[fn[0]] === "function") await w[fn[0]](fn[1]); } catch (e) { errs.push(fn[0] + ": " + String(e.message).slice(0, 80)); }
  }
  setTimeout(() => {
    const injected = d.querySelectorAll("img[onerror], svg[onload], a[href^='javascript'], [onerror], [onload]");
    const scriptsAdded = [...d.querySelectorAll("script")].filter(s => /__xss/.test(s.textContent)).length;
    const shown = (d.body.textContent.match(/onerror=|onload=|javascript:/g) || []).length;
    const items = d.querySelectorAll("#customerList li").length;
    console.log(page, "=> hostile text visibly rendered (escaped) x" + shown, "| inbox rows:", items, "| elements with injected handlers/javascript: URLs:", injected.length, "| injected <script>:", scriptsAdded, "| window.__xss fired:", JSON.stringify(w.__xss || null));
    injected.forEach(e => console.log("   INJECTED:", e.outerHTML.slice(0, 140)));
    console.log("   rule cards rendered:", d.querySelectorAll(".automation-title h3").length, "| first h3 innerHTML:", (d.querySelector(".automation-title h3")||{}).innerHTML);
    console.log("   functions exercised:", calls.filter(f => typeof w[f] === "function").join(","), "| js errors:", errs.length, errs.slice(0, 3));
    process.exit(0);
  }, 1500);
}, 1500);
