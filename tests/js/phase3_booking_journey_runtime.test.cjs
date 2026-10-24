"use strict";
/* Phase 3.27: execute actual booking helpers, no browser/npm dependencies. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "../..");
const timeJs = fs.readFileSync(path.join(root, "static/js/select_datetime.js"), "utf8");
const staffJs = fs.readFileSync(path.join(root, "static/js/select_stylist.js"), "utf8");

function functionSource(src, startName, nextName) {
  const start = src.indexOf("function " + startName + "(");
  const end = src.indexOf("function " + nextName + "(", start);
  assert.ok(start >= 0 && end > start, "could not isolate " + startName);
  return src.slice(start, end);
}
const escapeSource = functionSource(timeJs, "escapeBookingHtml", "bookingDigitMap");
const digits = functionSource(timeJs, "bookingDigitMap", "loadDataFromPage")
  + functionSource(timeJs, "toPersianDigits", "normalizeDigits");
const dateNumber = functionSource(timeJs, "formatAmount", "formatDuration");
const staffNumber = functionSource(staffJs, "formatAmount", "init");
const switcher = functionSource(timeJs, "renderServiceSwitcher", "renderStepContent");
const times = functionSource(timeJs, "renderTimeSlots", "updateContinueButton");
const summary = functionSource(timeJs, "buildSelectionSummaryLine", "calculateBookingTotals");

function run(code, context, method, ...args) {
  const sandbox = vm.createContext(context);
  vm.runInContext(code + "\nthis.__testFunction = " + method + ";", sandbox);
  return sandbox.__testFunction(...args);
}

test("HTML display helper escapes all five reserved characters without changing names", () => {
  const unsafe = String.raw`S'ara "<img src=x onerror=1>" & <svg> ${'نام'}`;
  const escaped = run(escapeSource, {}, "escapeBookingHtml", unsafe);
  assert.equal(escaped, "S&#39;ara &quot;&lt;img src=x onerror=1&gt;&quot; &amp; &lt;svg&gt; نام");
  assert.equal(run(escapeSource, {}, "escapeBookingHtml", null), "");
});

test("service switcher escapes hostile names and picked time exactly once", () => {
  const service = 'Service <img src=x onerror=1> & "title"';
  const time = '09:30 <svg/onload=1> &';
  const container = {innerHTML: "", querySelectorAll() {return [];}};
  const state = {
    selections: [{serviceId: "7", serviceName: service, serviceDuration: 30}],
    currentIndex: 0,
    picked: {"7": {date: "2026-11-03", time}},
  };
  run(escapeSource + switcher, {
    state,
    document: {getElementById(id) {assert.equal(id, "serviceSwitcher"); return container;}},
    getSelectionKey(selection) {return selection.serviceId;},
    formatGregorianToJalali() {return "۱۴۰۵/۰۸/۱۲";},
    formatDuration() {return "۳۰ دقیقه";},
  }, "renderServiceSwitcher");
  assert.ok(container.innerHTML.includes("Service &lt;img"));
  assert.ok(container.innerHTML.includes("&amp; &quot;title&quot;"));
  assert.ok(container.innerHTML.includes("09:30 &lt;svg/onload=1&gt; &amp;"));
  assert.ok(!container.innerHTML.includes("<img src="));
  assert.ok(!container.innerHTML.includes("<svg/onload"));
  assert.ok(!container.innerHTML.includes("&amp;lt;"), "must not double-escape");
  assert.equal(state.picked["7"].time, time);
});

test("summary keeps values raw until the one HTML sink", () => {
  const picked = {date: "2026-11-03", time: "09:00 & <bad>", end_time: "10:00 & <bad>"};
  const selection = {serviceName: "Cut", serviceDuration: 30, stylistName: "Ana"};
  const output = run(escapeSource + summary, {
    state: {currentIndex: 0, currentDate: null, currentTime: null, currentSlots: []},
    getPickedForIndex() {return picked;},
    formatDuration() {return "۳۰ دقیقه";},
    getSelectionPrice() {return 0;},
    formatAmount() {return "0";},
    formatGregorianToJalali() {return "۱۴۰۵/۰۸/۱۲";},
  }, "buildSelectionSummaryLine", selection, 0);
  assert.ok(output.pickedLabel.includes("09:00 & <bad> تا 10:00 & <bad>"));
  const result = run(escapeSource, {}, "escapeBookingHtml", output.pickedLabel);
  assert.ok(result.includes("09:00 &amp; &lt;bad&gt;"));
  assert.ok(!result.includes("&amp;amp;"));
  assert.equal(picked.time, "09:00 & <bad>");
});

test("time selection maintains native button state, escapes stylist and restores keyboard focus", () => {
  const selections = [];
  const fake = {
    markup: "", buttons: [],
    set innerHTML(value) {
      this.markup = value;
      this.buttons = [{
        dataset: {time: "10:00"}, handlers: {},
        addEventListener(type, handler) {this.handlers[type] = handler;},
        focus(options) {assert.equal(options.preventScroll, true); this.didFocus = true;},
      }];
      selections.push(this.buttons);
    },
    get innerHTML() {return this.markup;},
    querySelectorAll(selector) {
      assert.equal(selector, "[data-time-slot]");
      return this.buttons;
    },
  };
  const slots = [{time:"10:00", end_time:"10:45", stylistName:"<img src=x onerror=1> & Aya"}];
  const state = {currentTime: null, currentIndex: 0};
  let updates = 0;
  const runtime = vm.createContext({
    state,
    document: {getElementById(id) {assert.equal(id, "times"); return fake;}},
    groupSlotsByPeriod(values) {return [{key:"morning", icon:"fa-sun", label:"صبح", slots:values}];},
    toPersianDigits(value) {return String(value);},
    getPickedForIndex() {return null;},
    updateContinueButton() {updates += 1;},
    Array,
  });
  vm.runInContext(escapeSource + times + "\nthis.__render = renderTimeSlots;", runtime);
  runtime.__render(slots, {requestedStylistId:"any"}, false);
  assert.ok(fake.markup.includes("&lt;img src=x onerror=1&gt; &amp; Aya"));
  assert.ok(fake.markup.includes('role="group" aria-label="ساعت‌های آزاد"'));
  assert.ok(fake.markup.includes('aria-pressed="false"'));
  fake.buttons[0].handlers.click();
  assert.equal(state.currentTime, "10:00");
  assert.equal(updates, 1);
  assert.equal(selections.length, 2, "click triggers full rerender");
  assert.equal(selections[1][0].didFocus, true, "new selected button is focused");
  assert.ok(fake.markup.includes('aria-pressed="true"'));
});

test("fa/en/ar numeric formatting is language-specific; underlying ISO/time stays ASCII", () => {
  for (const [language, expectedDigits] of [
    ["fa", "۱۲۳۴۵۶۷۸۹۰"],
    ["en", "1234567890"],
    ["ar", "١٢٣٤٥٦٧٨٩٠"],
  ]) {
    const document = {documentElement: {lang: language}};
    assert.equal(run(digits, {document}, "toPersianDigits", "1234567890"), expectedDigits);
    const enAmount = run(dateNumber, {document, Intl, Number}, "formatAmount", 1234);
    const enStaff = run(staffNumber, {document, Intl, Number}, "formatAmount", 1234);
    assert.equal(enStaff, enAmount);
    assert.equal(enAmount.replace(/[^\p{Nd}]/gu, ""), expectedDigits.slice(0, 4));
  }
});
