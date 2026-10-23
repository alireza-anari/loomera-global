"use strict";
// Execute the real active verification/recovery inline scripts without external dependencies.
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "../..");
function inlineScript(page) {
  const html = fs.readFileSync(path.join(ROOT, "templates", "accounts", page + ".html"), "utf8");
  const match = html.match(/<script>([\s\S]*?)<\/script>/);
  assert.ok(match, page + " has executable inline script");
  return match[1];
}

function runVerify(withField = true) {
  const callbacks = {};
  const input = {
    value: "", focused: false, listeners: {},
    addEventListener(name, fn) {this.listeners[name] = fn;},
    focus() {this.focused = true;},
    change(value) {this.value = value; this.listeners.input?.({target: this});},
  };
  const document = {
    addEventListener(name, fn) {callbacks[name] = fn;},
    getElementById(name) {
      assert.equal(name, "id_active_code");
      return withField ? input : null;
    },
  };
  vm.runInNewContext(inlineScript("verify"), {document}, {filename:"verify.inline.js"});
  callbacks.DOMContentLoaded();
  return input;
}
test("OTP input receives focus when rendered", () => {
  assert.equal(runVerify().focused,true);
});
test("OTP script safely ignores missing input", () => {
  assert.doesNotThrow(() => runVerify(false));
});
for (const [value, expected] of [
  ["0 123-45a67", "01234567"],
  ["123456789012", "12345678"],
  ["<script>8&91", "891"],
  ["۷۸۹١٢34", "34"],
  ["", ""],
]) {
  test("OTP retains exactly ASCII digits and an eight-character ceiling: " + value, () => {
    const field = runVerify();
    field.change(value);
    assert.equal(field.value, expected);
  });
}
function createField(name,type) {
  const attrs={type};
  const classes=new Set();
  return {
    name, attrs, classes,
    getAttribute(key) {return attrs[key] || null;},
    setAttribute(key,val) {attrs[key]=val;},
    classList: {add(...names) {for(const n of names) classes.add(n);}},
  };
}
function runRecovery(fields, withForm = true) {
  const form={querySelectorAll(sel) {
    assert.equal(sel,"input, select, textarea");
    return fields;
  }};
  const document={querySelector(sel) {
    assert.equal(sel,"[data-auth-form]");
    return withForm ? form : null;
  }};
  vm.runInNewContext(inlineScript("remember_password"),{document}, {filename:"remember_password.inline.js"});
}
test("recovery targets only the named mobile input for forced numeric direction", () => {
  const fields=[
    createField("mobile_number","text"),
    createField("description","text"),
    createField("email","email"),
    createField("password","password"),
    createField("hidden","hidden"),
    createField("consent","checkbox"),
    createField("selection","radio"),
  ];
  runRecovery(fields);
  assert.equal(fields[0].attrs.dir,"ltr");
  for(const field of fields.slice(1)) assert.equal(field.attrs.dir,undefined);
  for(const field of fields.slice(0,4)) {
    assert.ok(field.classes.has("rounded-2xl"));
    assert.ok(field.classes.has("focus:border-loomera-primary"));
  }
  for(const field of fields.slice(4)) assert.equal(field.classes.size,0);
});
test("recovery gracefully skips a missing form", () => {
  assert.doesNotThrow(()=>runRecovery([],false));
});
test("recovery does not modify user-submitted field values", () => {
  const mobile = createField("mobile_number","text");
  mobile.value="<img onerror=alert(1)>09123";
  runRecovery([mobile]);
  assert.equal(mobile.value, "<img onerror=alert(1)>09123");
  assert.equal(mobile.attrs.dir,"ltr");
});
