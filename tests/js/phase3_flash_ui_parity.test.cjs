"use strict";
// Phase 3.16: exercise real feedback.js DOM creation, safe text and close controls.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const bridge = fs.readFileSync(path.join(root, "static/js/interactive_i18n.js"), "utf8");
const feedback = fs.readFileSync(path.join(root, "static/js/feedback.js"), "utf8");

const translations = {
  en: {
    "feedback.title.error": "Not completed",
    "feedback.title.success": "Completed",
    "feedback.title.warning": "Needs review",
    "feedback.title.info": "Information",
    "feedback.default.error": "This action could not be completed. Please try again.",
    "feedback.default.success": "The action completed successfully.",
    "feedback.default.warning": "This item needs review.",
    "feedback.default.info": "The information was updated.",
    "feedback.close": "Close message",
  },
  ar: {
    "feedback.title.error": "لم تكتمل العملية",
    "feedback.title.success": "تمت العملية",
    "feedback.title.warning": "تحتاج إلى مراجعة",
    "feedback.title.info": "معلومات",
    "feedback.default.error": "تعذّر إتمام العملية. يُرجى المحاولة مرة أخرى.",
    "feedback.default.success": "اكتملت العملية بنجاح.",
    "feedback.default.warning": "يحتاج هذا العنصر إلى مراجعة.",
    "feedback.default.info": "تم تحديث المعلومات.",
    "feedback.close": "إغلاق الرسالة",
  },
  fa: {
    "feedback.title.error": "انجام نشد",
    "feedback.title.success": "انجام شد",
    "feedback.title.warning": "نیاز به بررسی",
    "feedback.title.info": "اطلاع",
    "feedback.default.error": "انجام این عملیات با مشکل روبه‌رو شد. لطفاً دوباره تلاش کنید.",
    "feedback.default.success": "عملیات با موفقیت انجام شد.",
    "feedback.default.warning": "این مورد نیاز به بررسی دارد.",
    "feedback.default.info": "اطلاعات به‌روزرسانی شد.",
    "feedback.close": "بستن پیام",
  },
};
const tones = [
  ["error", "alert"],
  ["success", "status"],
  ["warning", "alert"],
  ["info", "status"],
];

class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.dataset = {};
    this.attrs = {};
    this.handlers = {};
    this.className = "";
    this.classList = {
      add: (...names) => {this.classes.push(...names);},
    };
    this.classes = [];
    this.textContent = "";
    this.innerHTML = "";
    this.removed = false;
  }
  setAttribute(name, value) { this.attrs[name] = value; }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); }
  addEventListener(event, cb) { this.handlers[event] = cb; }
  click() { this.handlers.click?.(); }
  remove() { this.removed = true; }
  querySelector(selector) {
    if (selector === "[data-flash-close]") return this.find(el => el.dataset.flashClose === "true");
    return null;
  }
  find(predicate) {
    if (predicate(this)) return this;
    for (const child of this.children) {
      const found = child.find(predicate);
      if (found) return found;
    }
    return null;
  }
}
function init(language) {
  const clock = [];
  const body = new Element("body");
  const catalog = language === "missing" ? null : {
    language, messages: translations[language],
  };
  const callbacks = {};
  const document = {
    body, readyState: "loading",
    getElementById(id) {
      assert.equal(id, "loomera-interactive-messages");
      return catalog ? {textContent: JSON.stringify(catalog)} : null;
    },
    querySelector(selector) {
      assert.equal(selector, "[data-lm-feedback-stack]");
      return body.children.find(child => child.dataset.lmFeedbackStack === "true") || null;
    },
    querySelectorAll(selector) {
      assert.equal(selector, "[data-flash-message]");
      return [];
    },
    createElement(name) {return new Element(name);},
    addEventListener(name,fn) {callbacks[name]=fn;},
  };
  const window = {setTimeout(callback, delay) {clock.push({callback,delay});}};
  vm.runInNewContext(bridge,{window, document}, {filename:"interactive_i18n.js"});
  vm.runInNewContext(feedback,{window, document, HTMLElement:Element}, {filename:"feedback.js"});
  return {window,body,clock,callbacks};
}
function nodeParts(node) {
  const close = node.find(el=>el.dataset.flashClose === "true");
  const title = node.find(el=>el.className === "text-xs font-black leading-5");
  const message = node.find(el=>el.className === "mt-0.5 text-sm font-bold leading-6");
  assert.ok(close);
  assert.ok(title);
  assert.ok(message);
  return {close,title,message};
}
for (const lang of ["fa","en","ar"]) {
  for (const [tone,role] of tones) {
    test(lang+" "+tone+" creates localized safe feedback without a runtime exception",()=>{
      const {window,body} = init(lang);
      const node=window.LoomeraFeedback[tone]("untrusted SQL Error: <script>secret</script>");
      const {close,title,message}=nodeParts(node);
      assert.equal(node.attrs.role,role);
      assert.equal(title.textContent,translations[lang]["feedback.title."+tone]);
      assert.equal(close.attrs["aria-label"],translations[lang]["feedback.close"]);
      assert.equal(message.textContent,translations[lang]["feedback.default."+tone]);
      assert.equal(body.children.length,1);
      assert.equal(body.children[0].children.length,1);
      assert.equal(node.innerHTML,"");
      assert.equal(message.innerHTML,"");
      assert.equal(close.type,"button");
      assert.ok(node.dataset.flashMessage);
    });
  }
}
test("English vetted notices show exactly, while unknown user data fails closed",()=>{
  const {window}=init("en");
  const vetted="This item needs review.";
  const shown=window.LoomeraFeedback.warning(vetted);
  assert.equal(nodeParts(shown).message.textContent,vetted);
  const bad=window.LoomeraFeedback.error("<img src=x onerror=alert(1)>");
  assert.equal(nodeParts(bad).message.textContent,translations.en["feedback.default.error"]);
});
test("Persian source feedback remains readable and preserves historical wording",()=>{
  const {window}=init("fa");
  assert.equal(nodeParts(window.LoomeraFeedback.success("فرایند با موفقیت ثبت شد.")).message.textContent,"فرایند با موفقیت ثبت شد.");
});
test("clicking close and scheduled dismissal keep existing DOM behavior",()=>{
  const {window,clock}=init("en");
  const node=window.LoomeraFeedback.info("",{duration:2500});
  assert.equal(clock.length,1);
  assert.equal(clock[0].delay,2500);
  const {close}=nodeParts(node);
  close.click();
  assert.equal(node.dataset.lmDismissing,"true");
  assert.equal(clock.length,2);
  assert.equal(clock[1].delay,300);
  clock[1].callback();
  assert.equal(node.removed,true);
  close.click();
  assert.equal(clock.length,2);
});
test("missing browser catalog preserves Persian fallback chrome",()=>{
  const {window}=init("missing");
  const node=window.LoomeraFeedback.error("raw traceback");
  const {close,title,message}=nodeParts(node);
  assert.equal(title.textContent,"انجام نشد");
  assert.equal(close.attrs["aria-label"],"بستن پیام");
  assert.equal(message.textContent,translations.fa["feedback.default.error"]);
});
