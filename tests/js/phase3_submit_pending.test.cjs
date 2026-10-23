"use strict";

// Dependency-free execution of the real form-interaction module in a DOM stub.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const source = fs.readFileSync(
  path.join(root, "static/js/pages/form_interactions.js"), "utf8"
);
const bridge = fs.readFileSync(
  path.join(root, "static/js/interactive_i18n.js"), "utf8"
);

const messages = {
  en: ["Saving…", "Registering…", "Sending…", "Creating…", "Signing in…", "Confirming…", "Activating…", "Deleting…", "Cancelling…", "Working…"],
  fa: ["در حال ذخیره…", "در حال ثبت…", "در حال ارسال…", "در حال ساخت…", "در حال ورود…", "در حال تأیید…", "در حال فعال‌سازی…", "در حال حذف…", "در حال لغو…", "در حال انجام…"],
  ar: ["جارٍ الحفظ…", "جارٍ التسجيل…", "جارٍ الإرسال…", "جارٍ الإنشاء…", "جارٍ تسجيل الدخول…", "جارٍ التأكيد…", "جارٍ التفعيل…", "جارٍ الحذف…", "جارٍ الإلغاء…", "جارٍ التنفيذ…"],
};
const keys = [
  "submit.saving", "submit.registering", "submit.sending", "submit.creating",
  "submit.logging_in", "submit.confirming", "submit.activating",
  "submit.deleting", "submit.cancelling", "submit.working",
];

class FakeElement {
  constructor(label, html = "<strong>Original action</strong>") {
    this.textContent = label;
    this.innerHTML = html;
    this.dataset = {};
    this.attributes = {};
    this.classes = new Set();
    this.classList = {
      add: (...items) => items.forEach(item => this.classes.add(item)),
      remove: (...items) => items.forEach(item => this.classes.delete(item)),
    };
    this.children = [];
    this.exempt = false;
  }
  matches() { return this.exempt; }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  replaceChildren(...children) {
    this.children = children;
    this.innerHTML = "[DOM child nodes, not interpreted HTML]";
  }
}
class FakeInput extends FakeElement {
  constructor(value) { super(value); this.value = value; }
}

function boot(language, catalog = true) {
  const win = {};
  const byLang = {};
  if (catalog) keys.forEach((key, i) => { byLang[key] = messages[language][i]; });
  const document = {
    getElementById: () => catalog ? {
      textContent: JSON.stringify({ language, messages: byLang }),
    } : null,
    createElement: (tag) => ({
      tagName: tag, className: "", textContent: "",
      attributes: {}, setAttribute(name, value) { this.attributes[name] = value; },
    }),
  };
  const ctx = {
    window: win, document,
    HTMLElement: FakeElement, HTMLInputElement: FakeInput,
  };
  vm.runInNewContext(bridge, ctx, {filename: "interactive_i18n.js"});
  const runnable = source.replace(
    "export default function initFormInteractions(",
    "function initFormInteractions("
  ) + "\nwindow.__submitTest = {markSubmitterPending, restoreSubmitter};";
  assert.ok(runnable.includes("window.__submitTest"));
  vm.runInNewContext(runnable, ctx, {filename: "form_interactions.js"});
  return win.__submitTest;
}

function labelFor(language, text, explicit) {
  const api = boot(language);
  const button = new FakeElement(text);
  if (explicit !== undefined) button.dataset.lmSubmittingLabel = explicit;
  api.markSubmitterPending(button);
  return {button, api, label: button.children[1]?.textContent};
}

test("English recognizes legacy Persian and English button actions", () => {
  for (const [original, expected] of [
    ["ذخیره اطلاعات", "Saving…"],
    ["Save changes", "Saving…"],
    ["ثبت‌نام", "Registering…"],
    ["ارسال کد تأیید", "Sending…"],
    ["Create", "Creating…"],
    ["ورود", "Signing in…"],
    ["تأیید", "Confirming…"],
    ["حذف", "Deleting…"],
    ["لغو", "Cancelling…"],
    ["Something custom", "Working…"],
  ]) {
    assert.equal(labelFor("en", original).label, expected, original);
  }
});

test("Arabic localized state recognizes native Arabic actions", () => {
  for (const [original, expected] of [
    ["حفظ التغييرات", "جارٍ الحفظ…"],
    ["تسجيل", "جارٍ التسجيل…"],
    ["إرسال الرمز", "جارٍ الإرسال…"],
    ["إنشاء", "جارٍ الإنشاء…"],
    ["دخول", "جارٍ تسجيل الدخول…"],
    ["تأكيد", "جارٍ التأكيد…"],
    ["تفعيل", "جارٍ التفعيل…"],
    ["حذف", "جارٍ الحذف…"],
    ["إلغاء", "جارٍ الإلغاء…"],
    ["other", "جارٍ التنفيذ…"],
  ]) {
    assert.equal(labelFor("ar", original).label, expected, original);
  }
});

test("Persian output keeps historical labels and explicit override", () => {
  assert.equal(labelFor("fa", "ویرایش").label, "در حال ذخیره…");
  assert.equal(labelFor("fa", "ارسال").label, "در حال ارسال…");
  assert.equal(labelFor("fa", "دیگر").label, "در حال انجام…");
  assert.equal(labelFor("fa", "دیگر", "در حال بررسی شخصی…").label, "در حال بررسی شخصی…");
});

test("untrusted explicit labels are not displayed as HTML or untranslated text", () => {
  const attack = '<img src=x onerror=alert(1)>';
  for (const language of ["en", "ar"]) {
    const {button, label} = labelFor(language, "Something custom", attack);
    assert.equal(label, messages[language][9]);
    assert.equal(button.children[0].tagName, "i");
    assert.equal(button.children[1].tagName, "span");
    assert.notEqual(button.innerHTML, attack);
  }
  const {button: fa, label: persian} = labelFor("fa", "ارسال", attack);
  assert.equal(persian, attack);
  assert.notEqual(fa.innerHTML, attack);
});

test("trusted explicit catalog label is accepted in English", () => {
  assert.equal(labelFor("en", "custom", "Sending…").label, "Sending…");
});

test("input submitter uses text value, restores it and resets busy state", () => {
  const api = boot("ar");
  const input = new FakeInput("حفظ");
  api.markSubmitterPending(input);
  assert.equal(input.value, "جارٍ الحفظ…");
  assert.equal(input.dataset.lmOriginalValue, "حفظ");
  assert.equal(input.attributes["aria-busy"], "true");
  assert.equal(input.attributes.disabled, "disabled");
  assert.equal(input.dataset.lmSubmitPending, "true");
  assert.equal(input.classes.has("lm-submit-pending"), true);
  api.restoreSubmitter(input);
  assert.equal(input.value, "حفظ");
  assert.equal(input.dataset.lmSubmitPending, "false");
  assert.equal(input.attributes["aria-busy"], undefined);
  assert.equal(input.attributes.disabled, undefined);
  assert.equal(input.classes.has("lm-submit-pending"), false);
});

test("button retains original HTML, is idempotent and restores on pageshow", () => {
  const api = boot("en");
  const btn = new FakeElement("Continue", '<span class="icon">Continue</span>');
  api.markSubmitterPending(btn);
  assert.equal(btn.children[1].textContent, "Working…");
  assert.equal(btn.dataset.lmOriginalHtml, '<span class="icon">Continue</span>');
  api.markSubmitterPending(btn);
  assert.equal(btn.dataset.lmOriginalHtml, '<span class="icon">Continue</span>');
  api.restoreSubmitter(btn);
  assert.equal(btn.innerHTML, '<span class="icon">Continue</span>');
  assert.equal(btn.dataset.lmOriginalHtml, undefined);
});

test("opt-out selector leaves button unchanged", () => {
  const api = boot("fa");
  const btn = new FakeElement("ذخیره");
  btn.exempt = true;
  api.markSubmitterPending(btn);
  assert.equal(btn.dataset.lmSubmitPending, undefined);
  assert.equal(btn.children.length, 0);
});

test("missing catalog safely uses legacy Persian fallback", () => {
  const api = boot("fa", false);
  const btn = new FakeElement("ارسال");
  api.markSubmitterPending(btn);
  assert.equal(btn.children[1].textContent, "در حال ارسال…");
});
