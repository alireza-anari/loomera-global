"use strict";
// Phase 3.28: exercise the actual compiled-catalog browser bridge and booking UI helper.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "../..");
const bridge = fs.readFileSync(path.join(root, "static/js/interactive_i18n.js"), "utf8");
const dateJs = fs.readFileSync(path.join(root, "static/js/select_datetime.js"), "utf8");
const staffJs = fs.readFileSync(path.join(root, "static/js/select_stylist.js"), "utf8");

const approved = {
  fa: { "booking.continue_time": "ادامه انتخاب زمان", "booking.morning": "صبح",
    "booking.available_times": "ساعت‌های قابل رزرو", "feedback.default.error": "انجام عملیات ممکن نشد." },
  en: { "booking.continue_time": "Continue to time selection", "booking.morning": "Morning",
    "booking.available_times": "Available appointment times", "feedback.default.error": "Action failed." },
  ar: { "booking.continue_time": "متابعة اختيار الوقت", "booking.morning": "الصباح",
    "booking.available_times": "الأوقات المتاحة للحجز", "feedback.default.error": "تعذّر إتمام العملية." },
};

function bootstrap(language, messages) {
  const window = {};
  const document = {
    getElementById(id) {
      assert.equal(id, "loomera-interactive-messages");
      return {textContent: JSON.stringify({language, messages})};
    },
  };
  vm.runInNewContext(bridge, {window, document}, {filename: "interactive_i18n.js"});
  return window.LoomeraI18n;
}
function runtimeHelper(source, afterName) {
  const first = source.indexOf("function bookingText(key, fallback)");
  const last = source.indexOf("function " + afterName + "(", first);
  assert.ok(first !== -1 && last > first);
  return source.slice(first, last);
}
const dateHelper = runtimeHelper(dateJs, "bookingDigitMap");
const staffHelper = runtimeHelper(staffJs, "init");
function translate(helper, api, key, fallback) {
  const context = {window: api ? {LoomeraI18n: api} : {}};
  vm.runInNewContext(helper + "\nthis.fn = bookingText;", context);
  return context.fn(key, fallback);
}

test("all three languages render reviewed booking text in both real JS helpers", () => {
  for (const language of ["fa", "en", "ar"]) {
    const api = bootstrap(language, approved[language]);
    assert.equal(api.language, language);
    for (const helper of [dateHelper, staffHelper]) {
      assert.equal(translate(helper, api, "continue_time", "ادامه انتخاب زمان"),
                   approved[language]["booking.continue_time"]);
      assert.equal(translate(helper, api, "morning", "صبح"),
                   approved[language]["booking.morning"]);
    }
  }
});

test("booking display copy never becomes a trusted server flash", () => {
  for (const language of ["fa", "en", "ar"]) {
    const api = bootstrap(language, approved[language]);
    assert.equal(api.isTrustedMessage(approved[language]["booking.morning"]), false);
    assert.equal(api.isTrustedMessage(approved[language]["booking.continue_time"]), false);
    assert.equal(api.isTrustedMessage(approved[language]["feedback.default.error"]), true);
    assert.equal(api.isTrustedMessage("Server error: 09123456789"), false);
  }
});

test("unreviewed keys, poisoned values and missing bridge use fixed Persian fallback", () => {
  assert.equal(translate(dateHelper, null, "continue_time", "ادامه انتخاب زمان"),
               "ادامه انتخاب زمان");
  const api = bootstrap("en", {
    "booking.continue_time": "<img src=x onerror=alert(1)>",
    "booking.morning": 28,
    "booking.extra": "x".repeat(310),
    "admin.token": "private",
    "feedback.default.error": "Action failed.",
  });
  assert.equal(api.text("admin.token", "safe"), "safe");
  assert.equal(api.text("booking.morning", "صبح"), "صبح");
  assert.equal(api.text("booking.extra", "safe"), "safe");
  assert.equal(translate(staffHelper, api, "morning", "صبح"), "صبح");
});

test("reviewed source uses display escaping and native slot/checkout contracts", () => {
  assert.ok(dateJs.includes("escapeBookingHtml(bookingText('available_times'"));
  assert.ok(dateJs.includes("escapeBookingHtml(bookingText('selected'"));
  assert.ok(dateJs.includes("bookingText('choose_date_time'"));
  assert.ok(staffJs.includes("bookingText('services_remaining'"));
  assert.ok(staffJs.includes("bookingText('professionals_selected'"));
  assert.ok(!bridge.includes("innerHTML"));
  assert.ok(dateJs.includes("bookingInput.value = JSON.stringify(bookingData)"));
  assert.ok(staffJs.includes("input.value = JSON.stringify(selections)"));
});

test("reject unsupported language catalog while retaining safe fallback", () => {
  const api = bootstrap("de", approved.en);
  assert.equal(api, undefined);
  assert.equal(translate(dateHelper, api, "continue_time", "ادامه انتخاب زمان"),
               "ادامه انتخاب زمان");
});
