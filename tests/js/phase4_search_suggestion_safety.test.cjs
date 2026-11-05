"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const test = require("node:test");

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.className = "";
    this.children = [];
    this._text = "";
    this.listeners = {};
  }
  appendChild(node) { this.children.push(node); return node; }
  get textContent() {
    return this._text + this.children.map((child) => child.textContent).join("");
  }
  set textContent(value) { this.children = []; this._text = String(value); }
  set innerHTML(value) {
    if (value) throw new Error("Untrusted suggestion markup reached innerHTML");
    this.children = []; this._text = "";
  }
  addEventListener(name, callback) { this.listeners[name] = callback; }
}
function load(path) {
  const document = { createElement: (tag) => new FakeElement(tag) };
  const context = vm.createContext({ document });
  const source = fs.readFileSync(path, "utf8").replace(/\bexport\s+(?=(?:async\s+)?function\s)/g, "");
  vm.runInContext(source, context, { filename: path });
  return { source, context };
}
const hostile = '"><img src=x onerror=alert(1)> & <svg/onload=alert(2)>';

test("public autocomplete renders all API names and metadata as literal text", () => {
  const { context } = load("static/js/search/autocomplete.js");
  const row = context.renderSuggestionItem(
    { value: hostile, type_label: hostile, meta: hostile }, () => {}
  );
  assert.equal(row.tagName, "LI");
  assert.equal(row.children[0].children[0].textContent, hostile);
  assert.equal(row.children[0].children[1].textContent, hostile);
  assert.equal(row.children[1].textContent, hostile);
  assert.equal(row.textContent, hostile.repeat(3));
  assert.equal(typeof row.listeners.click, "function");
});
test("search JSON suggestions, selection and active-filter labels use text nodes", () => {
  const { source, context } = load("static/js/search/filters.js");
  const container = new FakeElement("li");
  const label = context.appendSearchLabel(container, hostile, "text-primary", "span");
  assert.equal(label.textContent, hostile);
  assert.equal(container.textContent, hostile);
  assert.equal(label.children.length, 0);
  assert.doesNotMatch(source, /\b(?:button|row|item)\.innerHTML\s*=\s*\x60/);
  for (const fragment of [
    "appendSearchLabel(row, value,",
    "appendSearchLabel(item, serviceName,",
    "appendSearchLabel(item, salonName,",
    "appendSearchLabel(button, item.value,",
    "appendSearchLabel(button, chip?.dataset.serviceName",
  ]) assert.ok(source.includes(fragment), fragment);
  assert.match(source, /salonList\.innerHTML\s*=\s*payload\.html/);
});
test("map popup rejects code/data/protocol-relative and malformed image/detail URLs", () => {
  const { context } = load("static/js/search/map.js");
  assert.equal(context.safeSearchPopupUrl("/salons/12/", "#"), "/salons/12/");
  assert.equal(context.safeSearchPopupUrl("https://cdn.example.org/img.png"), "https://cdn.example.org/img.png");
  for (const url of [
    "javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:image/svg+xml,<svg>",
    "vbscript:msgbox(1)", "//attacker.example/a", "/\\attacker.example/a",
    "https://good.example/path\nbad", "ftp://example.org/a",
  ]) assert.equal(context.safeSearchPopupUrl(url, "#"), "#");
  const html = context.buildPopupContent({
    name: hostile, address: hostile, available_label: hostile,
    url: "javascript:alert(1)", image_url: "data:image/svg+xml,<svg>", id: hostile,
  });
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
  assert.doesNotMatch(html, /href="javascript:|src="data:|<img src=x onerror=/i);
  assert.match(html, /href="#"/);
});
test("map popup preserves safe route/image and escapes attribute values", () => {
  const { context } = load("static/js/search/map.js");
  const html = context.buildPopupContent({
    salon_name: 'A & "B"',
    detail_url: "/salons/12/?q=1&x=2",
    image_url: "https://cdn.example.org/a?one=1&two=2",
  });
  assert.match(html, /href="\/salons\/12\/\?q=1&amp;x=2"/);
  assert.match(html, /src="https:\/\/cdn\.example\.org\/a\?one=1&amp;two=2"/);
  assert.match(html, /A &amp; &quot;B&quot;/);
});
