"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "../..");
const read = (filename) => fs.readFileSync(path.join(root, filename), "utf8");

test("weekly-shifts template keeps zero-based Saturday-first hidden input wire keys", () => {
  const template = read("templates/dashboards/set_regular_shifts.html");
  const source = read("static/js/pages/set_regular_shifts.js");
  assert.match(template, /\{% for day in day_cards %\}/);
  assert.match(template, /name="day-\{\{ day\.index \}\}-shifts"/);
  assert.match(template, /data-day-hidden/);
  assert.match(source, /document\.querySelectorAll\("\[data-regular-day\]"\)/);
  assert.match(source, /dayCard\.querySelector\("\[data-day-hidden\]"\)/);
  assert.match(source, /hiddenInput\.value = values\.join\(","\)/);
  assert.match(source, /form\.addEventListener\("submit"/);
});

test("salon onboarding remains distinct persisted Saturday=1 through Friday=7", () => {
  const formTemplate = read("templates/dashboards/salon_profile_creator_step3.html");
  const partial = read("templates/dashboards/partials/onboarding_working_day.html");
  for (let day = 1; day <= 7; day += 1) {
    assert.ok(formTemplate.includes(`day_num=${day} `), `missing stored day ${day}`);
    assert.ok(formTemplate.includes(`form.day_${day}_active`));
  }
  assert.match(partial, /day_num/);
  assert.doesNotMatch(formTemplate, /day_num=0\b/);
  assert.doesNotMatch(formTemplate, /day_num=8\b/);
});

test("native JS Gregorian weekday naming is display-only, not a persisted weekday ID", () => {
  const source = read("static/js/pages/manual_booking.js");
  assert.match(source, /const weekdays = \[/);
  assert.match(source, /weekdays\[date\.getDay\(\)\]/);
  assert.match(source, /formatGregorianToJalali/);
  // JS Date.getDay() uses Sunday=0. It is NOT the salon opening-hour ID
  // and must never be used to prepare a day-N-shifts or persisted weekday field.
  assert.doesNotMatch(source, /day_of_week\s*[:=]\s*date\.getDay\(\)/);
  assert.doesNotMatch(source, /day-\$\{date\.getDay\(\)\}-shifts/);
});
