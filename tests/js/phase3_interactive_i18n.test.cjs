"use strict";

// Node's built-in test runner: no npm packages or browser/network dependency.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const bridge = fs.readFileSync(path.join(root, "static/js/interactive_i18n.js"), "utf8");
const feedback = fs.readFileSync(path.join(root, "static/js/feedback.js"), "utf8");

function init(payload) {
  const win = {};
  const document = {
    getElementById: () => payload === null ? null : {
      textContent: typeof payload === "string" ? payload : JSON.stringify(payload),
    },
    readyState: "loading",
    addEventListener: () => {},
  };
  vm.runInNewContext(bridge, {window: win, document}, {filename: "interactive_i18n.js"});
  vm.runInNewContext(feedback, {window: win, document}, {filename: "feedback.js"});
  return win;
}

const english = {
  language: "en",
  messages: {
    "feedback.title.error": "Not completed",
    "feedback.default.error": "This action could not be completed. Please try again.",
    "feedback.default.success": "The action completed successfully.",
    "feedback.close": "Close message",
    "validation.required": "This field is required.",
    "validation.too_short": "Enter at least {min} characters.",
    "validation.notice": "Please correct the highlighted fields.",
  },
};

const persian = {
  language: "fa",
  messages: {
    "feedback.default.error": "انجام این عملیات با مشکل روبه‌رو شد. لطفاً دوباره تلاش کنید.",
    "validation.required": "تکمیل این فیلد الزامی است.",
  },
};

const arabic = {
  language: "ar",
  messages: {
    "feedback.default.error": "تعذّر إتمام العملية. يُرجى المحاولة مرة أخرى.",
    "validation.required": "هذا الحقل مطلوب.",
  },
};

test("runtime exposes allowlisted immutable catalog and safe formatting", () => {
  const win = init(english);
  assert.equal(win.LoomeraI18n.language, "en");
  assert.equal(win.LoomeraI18n.text("validation.required"), "This field is required.");
  assert.equal(win.LoomeraI18n.text("unknown.key", "fallback"), "fallback");
  assert.equal(
    win.LoomeraI18n.format("validation.too_short", {min: 8}), "Enter at least 8 characters."
  );
  assert.equal(win.LoomeraI18n.isTrustedMessage("This field is required."), true);
  assert.equal(win.LoomeraI18n.isTrustedMessage("Arbitrary server message"), false);
  assert.equal(Object.isFrozen(win.LoomeraI18n), true);
});

test("English flash accepts vetted UI notice but not arbitrary server details", () => {
  const win = init(english);
  assert.equal(
    win.LoomeraFeedback.safeMessage("Please correct the highlighted fields.", "error"),
    "Please correct the highlighted fields."
  );
  assert.equal(
    win.LoomeraFeedback.safeMessage("Database Error: SELECT * FROM users", "error"),
    english.messages["feedback.default.error"]
  );
  assert.equal(
    win.LoomeraFeedback.safeMessage("Unauthorized backend text", "error"),
    english.messages["feedback.default.error"]
  );
});

test("Arabic flash uses catalog-provided generic fallback", () => {
  const win = init(arabic);
  assert.equal(win.LoomeraI18n.language, "ar");
  assert.equal(win.LoomeraI18n.text("validation.required"), "هذا الحقل مطلوب.");
  assert.equal(
    win.LoomeraFeedback.safeMessage("backend exception", "error"),
    arabic.messages["feedback.default.error"]
  );
});

test("Persian deployment keeps the historical feedback sanitizer behavior", () => {
  const win = init(persian);
  assert.equal(
    win.LoomeraFeedback.safeMessage("نوبت شما ثبت شد.", "success"),
    "نوبت شما ثبت شد."
  );
  assert.equal(
    win.LoomeraFeedback.safeMessage("ValueError: private stack", "error"),
    persian.messages["feedback.default.error"]
  );
});

test("missing, malformed, or disabled locale payload fails closed", () => {
  for (const payload of [null, "{malformed", {language: "fr", messages: {}}]) {
    const win = init(payload);
    assert.equal(win.LoomeraI18n, undefined);
    assert.equal(
      win.LoomeraFeedback.safeMessage("انجام شد", "success"),
      "انجام شد"
    );
  }
});

test("catalog ignores unknown message keys and non-string values", () => {
  const win = init({
    language: "en",
    messages: {
      "validation.required": "This field is required.",
      "admin.token": "secret",
      "feedback.bad": {content: "unsafe"},
      "__proto__": "polluted",
    },
  });
  assert.equal(win.LoomeraI18n.text("admin.token", "safe"), "safe");
  assert.equal(win.LoomeraI18n.text("feedback.bad", "safe"), "safe");
  assert.equal(win.LoomeraI18n.text("__proto__", "safe"), "safe");
  assert.equal(win.LoomeraI18n.text("validation.required"), "This field is required.");
});
