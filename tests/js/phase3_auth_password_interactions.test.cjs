"use strict";
/* Phase 3.13 — execute the four real active auth inline scripts, without a browser. */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "../..");
const PAGES = ["login", "register", "customer_signup", "stylist_signup"];
const TRANSLATIONS = {
  en: {
    "password.show": "Show password",
    "password.hide": "Hide password",
    "password.strength.strong": "Strong password.",
    "password.strength.acceptable": "Acceptable password; consider making it stronger.",
    "password.strength.guidance": "At least 8 characters; numbers, letters and symbols make it stronger.",
    "password.too_short": "Password must be at least 8 characters long.",
  },
  ar: {
    "password.show": "إظهار كلمة المرور",
    "password.hide": "إخفاء كلمة المرور",
    "password.strength.strong": "كلمة المرور قوية.",
    "password.strength.acceptable": "كلمة المرور مقبولة، لكن يُفضّل جعلها أقوى.",
    "password.strength.guidance": "ثمانية أحرف على الأقل؛ الأرقام والحروف والرموز تجعلها أقوى.",
    "password.too_short": "يجب أن تتكون كلمة المرور من 8 أحرف على الأقل.",
  },
};
const FA = {
  manager: "حداقل ۸ کاراکتر؛ ترکیب حروف و عدد بهتر است.",
  customer: "حداقل ۸ کاراکتر؛ بهتر است از حروف و عدد استفاده کنی.",
};
function prepare(page, language) {
  const html = fs.readFileSync(path.join(ROOT, "templates/accounts", page + ".html"), "utf8");
  const block = html.match(/\{% block js %\}\s*<script>([\s\S]*?)<\/script>\s*\{% endblock %\}/);
  assert.ok(block, page + " must have a self-contained page script");
  const listeners = Object.create(null);
  const inputs = {};
  for (const id of ["id_password", "id_password1", "id_password2", "id_mobile_number"]) {
    inputs[id] = {
      id, type: id === "id_mobile_number" ? "tel" : "password", value: "",
      addEventListener(type, fn) { this[type] = fn; },
      dispatch(type) { this[type]?.({target:this}); },
    };
  }
  const toggles = (page === "login" ? ["id_password"] : ["id_password1", "id_password2"]).map(id => {
    const attrs = {};
    const classes = new Set(["fa-eye"]);
    const icon = { classList: { toggle(c) { classes.has(c) ? classes.delete(c) : classes.add(c); }, contains(c) { return classes.has(c); } } };
    return {
      dataset: {input:id}, attrs, icon, handlers: {},
      setAttribute(k,v) {attrs[k]=v;},
      querySelector(selector) { assert.equal(selector,"i"); return icon; },
      addEventListener(type,fn) {this.handlers[type]=fn;},
      click() {this.handlers.click.call(this,{preventDefault() {}});},
    };
  });
  const hint = {textContent: "static default"};
  const bars = [{className:""},{className:""},{className:""}];
  const document = {
    addEventListener(event,cb) {listeners[event]=cb;},
    querySelectorAll(selector) {
      if(selector===".toggle-password") return toggles;
      if(selector==="[data-strength-bar]") return page==="register" || page==="stylist_signup" ? bars : [];
      throw Error("unexpected selector "+selector);
    },
    querySelector(selector) {
      if(selector==="[data-password-hint]") return hint;
      throw Error("unexpected selector "+selector);
    },
    getElementById(id) {return inputs[id] || null;},
  };
  const translations = TRANSLATIONS[language] || {};
  const window = language === "missing" ? {} : { LoomeraI18n: {
    language, text(key,fallback) {return translations[key] || fallback;},
  }};
  vm.runInNewContext(block[1],{document,window,Array}, {filename:page + ".inline.js"});
  assert.equal(typeof listeners.DOMContentLoaded,"function");
  listeners.DOMContentLoaded();
  return {inputs,toggles,hint,bars};
}

for(const page of PAGES) {
  for(const language of ["en","ar","fa","missing"]) {
    test(page+" "+language+" show/hide is accessible and does not alter field values",()=>{
      const ui=prepare(page,language);
      const translations=TRANSLATIONS[language];
      const expectedShow=translations?.["password.show"] || "نمایش رمز عبور";
      const expectedHide=translations?.["password.hide"] || "مخفی کردن رمز عبور";
      for (const toggle of ui.toggles) {
        const field=ui.inputs[toggle.dataset.input];
        field.value="safely<not HTML>&";
        assert.equal(toggle.attrs["aria-label"],expectedShow);
        assert.equal(field.type,"password");
        toggle.click();
        assert.equal(field.type,"text");
        assert.equal(field.value,"safely<not HTML>&");
        assert.equal(toggle.attrs["aria-pressed"],"true");
        assert.equal(toggle.attrs["aria-label"],expectedHide);
        assert.ok(toggle.icon.classList.contains("fa-eye-slash"));
        toggle.click();
        assert.equal(field.type,"password");
        assert.equal(toggle.attrs["aria-pressed"],"false");
        assert.equal(toggle.attrs["aria-label"],expectedShow);
        assert.ok(toggle.icon.classList.contains("fa-eye"));
      }
    });
  }
}

for (const page of ["register","stylist_signup"]) {
  for (const language of ["en","ar","fa","missing"]) {
    test(page+" "+language+" strength hints and scoring preserve thresholds",()=>{
      const ui=prepare(page,language);
      const lang=TRANSLATIONS[language];
      assert.equal(ui.hint.textContent, lang?.["password.strength.guidance"] || FA.manager);
      const field=ui.inputs.id_password1;
      field.value="x";field.dispatch("input");
      assert.equal(ui.hint.textContent,lang?.["password.strength.guidance"] || FA.manager);
      assert.equal(ui.bars.filter(x=>x.className==="bg-loomera-primary").length,0);
      field.value="Pass1234";field.dispatch("input");
      assert.equal(ui.hint.textContent,lang?.["password.strength.acceptable"] || "رمز قابل قبول است؛ بهتر است قوی‌تر شود.");
      assert.equal(ui.bars.filter(x=>x.className==="bg-loomera-primary").length,2);
      field.value="Pass1234!long";field.dispatch("input");
      assert.equal(ui.hint.textContent,lang?.["password.strength.strong"] || "رمز قوی است.");
      assert.equal(ui.bars.filter(x=>x.className==="bg-loomera-primary").length,3);
    });
  }
}
for(const language of ["en","ar","fa","missing"]) {
  test("customer_signup "+language+" only measures minimum password length",()=>{
    const ui=prepare("customer_signup",language);
    const lang=TRANSLATIONS[language];
    assert.equal(ui.hint.textContent,lang?.["password.strength.guidance"] || FA.customer);
    ui.inputs.id_password1.value="short";ui.inputs.id_password1.dispatch("input");
    assert.equal(ui.hint.textContent,lang?.["password.too_short"] || "حداقل ۸ کاراکتر وارد کن.");
    ui.inputs.id_password1.value="12345678";ui.inputs.id_password1.dispatch("input");
    assert.equal(ui.hint.textContent,lang?.["password.strength.acceptable"] || "طول رمز عبور مناسب است.");
  });
}
for (const page of PAGES){
  test(page+" preserves mobile-number digit filtering",()=>{
    const ui=prepare(page,"en");
    const field=ui.inputs.id_mobile_number;
    field.value="09x12-345۶78901";
    field.dispatch("input");
    assert.equal(field.value,page==="stylist_signup"?"09123457890":"091234578901");
  });
}
