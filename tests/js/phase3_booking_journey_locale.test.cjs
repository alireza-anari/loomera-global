"use strict";
/* Phase 3.29 — executed booking calendar locale and trust boundary checks. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "../..");
const bridge = fs.readFileSync(path.join(root, "static/js/interactive_i18n.js"), "utf8");
const datetime = fs.readFileSync(path.join(root, "static/js/select_datetime.js"), "utf8");
const keyStart = datetime.indexOf("  function bookingText(key, fallback)");
const keyEnd = datetime.indexOf("  function bookingDigitMap()", keyStart);
const escapeStart = datetime.indexOf("  function escapeBookingHtml(value)");
const escapeEnd = datetime.indexOf("  function bookingText(key, fallback)", escapeStart);
assert.ok(keyStart >= 0 && keyEnd > keyStart && escapeEnd > escapeStart);
const helper = datetime.slice(keyStart, keyEnd);
const escaper = datetime.slice(escapeStart, escapeEnd);

const data = {
  fa: {
    "booking.available_ninety_days": "روزهای آزاد و غیرفعال این خدمت در ۹۰ روز آینده",
    "booking.choose_other_day_action": "برای این خدمت روز دیگری انتخاب می‌کنم",
    "booking.default_same_day": "پیش‌فرض این خدمت همان روز",
    "booking.suggested": "پیشنهادی",
  },
  en: {
    "booking.available_ninety_days": "Available and unavailable dates for this service over the next 90 days",
    "booking.choose_other_day_action": "I will choose another day for this service",
    "booking.default_same_day": "The default date for this service is",
    "booking.suggested": "Suggested",
  },
  ar: {
    "booking.available_ninety_days": "التواريخ المتاحة وغير المتاحة لهذه الخدمة خلال الأيام التسعين القادمة",
    "booking.choose_other_day_action": "سأختار يومًا آخر لهذه الخدمة",
    "booking.default_same_day": "التاريخ الافتراضي لهذه الخدمة هو",
    "booking.suggested": "مقترح",
  },
};

function init(language, messages) {
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
function getText(api, key, fallback) {
  const context = {window: api ? {LoomeraI18n: api} : {}};
  vm.runInNewContext(helper + "\nthis.lookup = bookingText;", context);
  return context.lookup(key, fallback);
}
function html(value) {
  const context = {};
  vm.runInNewContext(escaper + "\nthis.clean = escapeBookingHtml;", context);
  return context.clean(value);
}

test("new calendar labels resolve to the active fa/en/ar gettext bridge", () => {
  for (const lang of ["fa", "en", "ar"]) {
    const api = init(lang, data[lang]);
    assert.equal(api.language, lang);
    for (const [qualified, reviewed] of Object.entries(data[lang])) {
      const name = qualified.slice("booking.".length);
      assert.equal(getText(api, name, "fallback"), reviewed);
    }
  }
});

test("new booking display strings cannot be promoted to trusted server feedback", () => {
  for (const lang of ["fa", "en", "ar"]) {
    const api = init(lang, {
      ...data[lang],
      "feedback.default.error": "Reviewed feedback",
    });
    for (const value of Object.values(data[lang])) {
      assert.equal(api.isTrustedMessage(value), false);
    }
    assert.equal(api.isTrustedMessage("Reviewed feedback"), true);
    assert.equal(api.isTrustedMessage("Account: 09123456789"), false);
  }
});

test("calendar copy interpolated in HTML remains escaped once and preserves original text", () => {
  const unsafe = "روز پیشنهادی <img src=x onerror=1> & 'Team'";
  assert.equal(html(unsafe), "روز پیشنهادی &lt;img src=x onerror=1&gt; &amp; &#39;Team&#39;");
  for (const lang of ["fa", "en", "ar"]) {
    const api = init(lang, {
      ...data[lang],
      "booking.choose_other_day_action": unsafe,
    });
    const raw = getText(api, "choose_other_day_action", "fallback");
    assert.equal(raw, "fallback", "markup-bearing browser text is rejected");
    assert.ok(!html(raw).includes("<img"));
    assert.ok(html(unsafe).includes("&lt;img"));
  }
});

test("missing bridge, unsupported language and malformed values fail closed", () => {
  assert.equal(getText(null, "suggested", "پیشنهادی"), "پیشنهادی");
  assert.equal(init("de", data.en), undefined);
  const api = init("en", {
    "booking.suggested": 123,
    "booking.no_room": "<b>invalid</b>",
    "booking.calendar_guidance": "x".repeat(301),
  });
  assert.equal(getText(api, "suggested", "پیشنهادی"), "پیشنهادی");
  assert.equal(getText(api, "no_room", "بدون جای خالی"), "بدون جای خالی");
  assert.equal(getText(api, "calendar_guidance", "fallback"), "fallback");
});
