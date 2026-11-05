"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function mapContext(direction) {
  const src = fs.readFileSync("static/js/search/map.js", "utf8")
    .replace(/\bexport\s+(?=(?:async\s+)?function\s)/g, "");
  const document = {
    documentElement: { lang: direction === "ltr" ? "en" : "ar", dir: direction },
    getElementById: () => null,
  };
  const ctx = vm.createContext({ document });
  vm.runInContext(src, ctx);
  return ctx;
}

test("translated server availability status stays visible in map popup", () => {
  const ctx = mapContext("ltr");
  const result = ctx.buildPopupContent({
    id: 7,
    salon_name: "Professional name",
    detail_url: "/salons/7/",
    available_label: "First available at 09:30",
  });
  assert.match(result, /First available at 09:30/);
  assert.match(result, /href="\/salons\/7\/"/);
  assert.match(result, /dir="ltr"/);
});

test("available slot text is escaped even when API content is hostile", () => {
  const ctx = mapContext("rtl");
  const result = ctx.buildPopupContent({
    salon_name: "صالون",
    available_label: "أول موعد متاح <svg onload=alert(1)>",
  });
  assert.match(result, /dir="rtl"/);
  assert.match(result, /&lt;svg onload=alert\(1\)&gt;/);
  assert.doesNotMatch(result, /<svg onload=/);
});
