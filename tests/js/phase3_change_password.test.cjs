"use strict";

// Execute the real inline change-password page script against an isolated DOM.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const template = fs.readFileSync(
  path.join(root, "templates/accounts/change_password.html"), "utf8"
);
const scriptMatch = template.match(
  /\{% block js %\}[\s\S]*?<script>([\s\S]*?)<\/script>/
);
assert.ok(scriptMatch, "active password template must expose its inline JS");
const source = scriptMatch[1];
const bridge = fs.readFileSync(
  path.join(root, "static/js/interactive_i18n.js"), "utf8"
);
const feedback = fs.readFileSync(
  path.join(root, "static/js/feedback.js"), "utf8"
);

const messages = {
  en: {
    "password.strength.strong": "Strong password.",
    "password.strength.acceptable": "Acceptable password; consider making it stronger.",
    "password.strength.guidance": "At least 8 characters; numbers, letters and symbols make it stronger.",
    "password.show": "Show password",
    "password.hide": "Hide password",
    "password.mismatch": "Passwords do not match.",
    "password.too_short": "Password must be at least 8 characters long.",
    "feedback.default.error": "This action could not be completed. Please try again.",
  },
  ar: {
    "password.strength.strong": "كلمة المرور قوية.",
    "password.strength.acceptable": "كلمة المرور مقبولة، لكن يُفضّل جعلها أقوى.",
    "password.strength.guidance": "ثمانية أحرف على الأقل؛ الأرقام والحروف والرموز تجعلها أقوى.",
    "password.show": "إظهار كلمة المرور",
    "password.hide": "إخفاء كلمة المرور",
    "password.mismatch": "كلمتا المرور غير متطابقتين.",
    "password.too_short": "يجب أن تتكون كلمة المرور من 8 أحرف على الأقل.",
    "feedback.default.error": "تعذّر إتمام العملية. يُرجى المحاولة مرة أخرى.",
  },
  fa: {
    "password.strength.strong": "رمز عبور قوی است.",
    "password.strength.acceptable": "رمز قابل قبول است؛ بهتر است قوی‌تر شود.",
    "password.strength.guidance": "حداقل ۸ کاراکتر؛ استفاده از عدد، حروف و نشانه‌ها رمز را قوی‌تر می‌کند.",
    "password.show": "نمایش رمز عبور",
    "password.hide": "مخفی کردن رمز عبور",
    "password.mismatch": "رمز عبور و تکرار آن مطابقت ندارند",
    "password.too_short": "رمز عبور باید حداقل ۸ کاراکتر باشد",
    "feedback.default.error": "انجام این عملیات با مشکل روبه‌رو شد. لطفاً دوباره تلاش کنید.",
  },
};

function bootstrap(lang, withCatalog = true) {
  const events = Object.create(null);
  const flash = [];
  const strengthHint = { textContent: "" };
  const bars = Array.from({length: 3}, () => ({className: ""}));
  const fields = {};
  for (const id of ["newPassword", "confirmPassword", "currentPassword"]) {
    fields[id] = {
      value: "", attributes: {type: "password"}, events: Object.create(null),
      getAttribute(key) { return this.attributes[key] || null; },
      setAttribute(key, value) { this.attributes[key] = value; },
      addEventListener(key, callback) { this.events[key] = callback; },
      focus(options) { this.focused = options; },
    };
  }
  const form = {
    addEventListener(name, callback) { events["form." + name] = callback; },
  };
  fields.changePasswordForm = form;

  const toggleIcon = {className: "fa-solid fa-eye"};
  const toggle = {
    attrs: {"data-target": "newPassword", "aria-controls": "newPassword"},
    getAttribute(name) { return this.attrs[name] || null; },
    setAttribute(name, value) { this.attrs[name] = value; },
    querySelector(name) { return name === "i" ? toggleIcon : null; },
  };
  const document = {
    readyState: "loading",
    getElementById(id) {
      if (id === "loomera-interactive-messages") {
        return withCatalog
          ? {textContent: JSON.stringify({language: lang, messages: messages[lang]})}
          : null;
      }
      return fields[id] || null;
    },
    querySelector(selector) {
      return selector === "[data-password-strength-hint]" ? strengthHint : null;
    },
    querySelectorAll(selector) {
      return selector === "[data-password-strength-bar]" ? bars : [];
    },
    addEventListener(event, callback) { events[event] = callback; },
  };
  const win = {};
  const ctx = {window: win, document};
  vm.runInNewContext(bridge, ctx, {filename: "interactive_i18n.js"});
  vm.runInNewContext(feedback, ctx, {filename: "feedback.js"});
  const original = win.LoomeraFeedback;
  win.LoomeraFeedback = {
    error(value) {
      flash.push({
        input: value,
        output: original.safeMessage(value, "error"),
      });
    },
  };
  vm.runInNewContext(source, ctx, {filename: "change_password_inline.js"});
  events.DOMContentLoaded();
  return {
    fields, bars, strengthHint, flash, toggle, toggleIcon, events, win,
    // The page finds the actual text-only element via querySelector;
    // this getter is returned separately to catch unintended extra DOM writes.
    update(password) {
      fields.newPassword.value = password;
      fields.newPassword.events.input();
    },
    submit(first, second) {
      fields.newPassword.value = first;
      fields.confirmPassword.value = second;
      const event = {defaultPrevented: false, preventDefault() {this.defaultPrevented = true;}};
      events["form.submit"](event);
      return event;
    },
    clickToggle() {
      let prevented = false;
      events.click({
        target: {closest(selector) {
          assert.equal(selector, "[data-password-toggle]");
          return toggle;
        }},
        preventDefault() {prevented = true;},
      });
      return prevented;
    },
  };
}

// Inject a selector for the one strength text element without changing
// browser logic; the real handler looks it up at DOMContentLoaded.
function start(lang, withCatalog = true) {
  const app = bootstrap(lang, withCatalog);
  return app;
}

test("English password strength uses the unchanged 0/2/3 scoring thresholds", () => {
  const app = start("en");
  app.update("abcdefgh1");
  assert.equal(app.strengthHint.textContent, messages.en["password.strength.acceptable"]);
  assert.equal(app.bars.filter(x => x.className.includes("bg-loomera-primary")).length, 2);
  app.update("abcdefgh1!");
  assert.equal(app.strengthHint.textContent, messages.en["password.strength.strong"]);
  assert.equal(app.bars.filter(x => x.className.includes("bg-loomera-primary")).length, 3);
  app.update("abc");
  assert.equal(app.strengthHint.textContent, messages.en["password.strength.guidance"]);
  assert.equal(app.bars.filter(x => x.className.includes("bg-loomera-primary")).length, 0);
});

test("English and Arabic mismatched passwords prevent submission with trusted copy", () => {
  for (const lang of ["en", "ar"]) {
    const app = start(lang);
    app.update("abcdefgh1!");
    assert.equal(app.strengthHint.textContent, messages[lang]["password.strength.strong"]);
    const event = app.submit("abcdefgh123", "another-password");
    assert.equal(event.defaultPrevented, true);
    assert.equal(app.flash.length, 1);
    assert.equal(app.flash[0].input, messages[lang]["password.mismatch"]);
    assert.equal(app.flash[0].output, messages[lang]["password.mismatch"]);
  }
});

test("English and Arabic short password retains minimum-eight policy", () => {
  for (const lang of ["en", "ar"]) {
    const app = start(lang);
    const event = app.submit("abc1234", "abc1234");
    assert.equal(event.defaultPrevented, true);
    assert.equal(app.flash[0].input, messages[lang]["password.too_short"]);
    assert.equal(app.flash[0].output, messages[lang]["password.too_short"]);
  }
});

test("valid client-side passwords are allowed through without flash", () => {
  const app = start("en");
  const event = app.submit("abcdefgh123!", "abcdefgh123!");
  assert.equal(event.defaultPrevented, false);
  assert.equal(app.flash.length, 0);
});

test("language-specific toggle preserves input type, pressed flag and icon", () => {
  for (const lang of ["en", "ar", "fa"]) {
    const app = start(lang);
    assert.equal(app.clickToggle(), true);
    assert.equal(app.fields.newPassword.attributes.type, "text");
    assert.equal(app.toggle.attrs["aria-pressed"], "true");
    assert.equal(app.toggle.attrs["aria-label"], messages[lang]["password.hide"]);
    assert.match(app.toggleIcon.className, /fa-eye-slash/);
    assert.equal(app.clickToggle(), true);
    assert.equal(app.fields.newPassword.attributes.type, "password");
    assert.equal(app.toggle.attrs["aria-pressed"], "false");
    assert.equal(app.toggle.attrs["aria-label"], messages[lang]["password.show"]);
    assert.match(app.toggleIcon.className, /fa-eye/);
  }
});

test("Persian fallback works if the translation bridge is absent", () => {
  const app = start("fa", false);
  app.update("abcdefgh1!");
  const event = app.submit("abcdefgh123", "does-not-match");
  assert.equal(event.defaultPrevented, true);
  assert.equal(app.flash[0].input, "رمز عبور و تکرار آن مطابقت ندارند");
  assert.equal(app.clickToggle(), true);
  assert.equal(app.toggle.attrs["aria-label"], "مخفی کردن رمز عبور");
});

test("passwords remain opaque text; no input values become DOM HTML", () => {
  const app = start("en");
  const attack = "<img src=x onerror=alert(1)>";
  app.update(attack);
  assert.equal(app.fields.newPassword.value, attack);
  const event = app.submit(attack, "other");
  assert.equal(event.defaultPrevented, true);
  assert.equal(app.flash[0].output, "Passwords do not match.");
  assert.equal(app.bars.length, 3);
});
