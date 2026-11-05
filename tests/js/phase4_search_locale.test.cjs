"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
function load(path, dataset) {
  const document = {
    documentElement: {lang: "en", dir: "ltr"},
    getElementById: () => ({dataset}),
  };
  const src = fs.readFileSync(path, "utf8").replace(/\bexport\s+(?=(?:async\s+)?function)/g, "");
  const ctx = vm.createContext({document});
  vm.runInContext(src, ctx);
  return ctx;
}
test("live filter messages are selected from active locale", () => {
  const ctx = load("static/js/search/filters.js", {nearMe:"Near me", serviceCount:"{count} services"});
  assert.equal(ctx.searchText("nearMe", "نزدیک من"), "Near me");
  assert.equal(ctx.searchFormat("serviceCount", "{count} خدمت", {count:2}), "2 services");
});
test("popup preserves escaped merchant names and follows English direction", () => {
  const ctx = load("static/js/search/map.js", {viewSalon:"View salon", toman:"Toman", from:"From"});
  const html = ctx.buildPopupContent({salon_name:"A & B", detail_url:"/salons/1/", search_primary_price:2500});
  assert.match(html, /dir="ltr"/);
  assert.match(html, /A &amp; B/);
  assert.match(html, /View salon/);
  assert.match(html, /Toman/);
  assert.match(html, /href="\/salons\/1\/"/);
});

test("translated geolocation copy never enters suggestion innerHTML", () => {
  const source = fs.readFileSync("static/js/search/filters.js", "utf8");
  assert.doesNotMatch(source, /nearMeRow\.innerHTML\s*=/);
  assert.match(source, /appendSearchLabel\(nearMeTitle,/);
});
