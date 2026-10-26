"use strict";
// Execute the production controller. This unit DOM models native inert focus;
// actual browser behavior is checked by the Chromium suite, not this model.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../templates/orders/appointment_detail.html'), 'utf8');
let controller = source.slice(source.indexOf("  const manageModal ="), source.indexOf('  window.addToCalendar ='));
// Include trailing page keyboard listeners, which must not dismiss a second
// dialog after the stack controller has already handled Escape.
const tailKeydown = source.lastIndexOf("  document.addEventListener('keydown'");
if (tailKeydown > source.indexOf('  window.addToCalendar =')) {
  controller += source.slice(tailKeydown, source.lastIndexOf('</script>'));
}
function setup() {
  const handlers = {}; const listeners = {};
  let document;
  class Element {
    constructor(id, parent = null) {
      this.id = id; this.parentElement = parent; this.children = []; this.attrs = {};
      this.style = {}; this.isConnected = true; this.disabled = false; this.tabIndex = 0;
      this.classList = {add() {}, remove() {}};
      if (parent) parent.children.push(this);
    }
    contains(node) { return node === this || this.children.some(child => child.contains(node)); }
    getAttribute(key) { return this.attrs[key] ?? null; }
    setAttribute(key, value) { this.attrs[key] = value; }
    removeAttribute(key) { delete this.attrs[key]; }
    hasAttribute(key) { return key in this.attrs; }
    closest(selector) { return selector === '[inert]' && this.hasAttribute('inert') ? this : this.parentElement?.closest(selector); }
    getClientRects() { return [1]; }
    querySelector() { return this.title || null; }
    querySelectorAll() { return this.controls || []; }
    focus() {
      if (this.closest('[inert]')) return;
      document.activeElement = this;
      handlers.focusin?.({target: this});
    }
  }
  const body = new Element('body'); body.style.overflow = 'auto';
  const header = new Element('header', body);
  const main = new Element('main', body);
  const content = new Element('content', main);
  const opener = new Element('opener', content);
  const existing = new Element('existing', main); existing.setAttribute('inert', 'original');
  const manage = new Element('manageModal', main);
  const review = new Element('reviewModal', main);
  for (const modal of [manage, review]) {
    modal.setAttribute('aria-hidden', 'true');
    modal.title = new Element(modal.id + 'Title', modal); modal.title.tabIndex = -1;
    modal.controls = [new Element(modal.id + 'Close', modal)];
  }
  document = {body, activeElement: opener,
    getElementById: id => id === 'main-content' ? main : id === manage.id ? manage : review,
    querySelector: () => null,
    addEventListener: (type, callback) => {
      (listeners[type] ||= []).push(callback);
      handlers[type] = event => listeners[type].forEach(listener => listener(event));
    },
  };
  const window = {getComputedStyle: () => ({visibility: 'visible'})};
  vm.runInNewContext(controller, {document, window});
  return {document, window, header, main, content, opener, existing, manage, review, handlers};
}
test('open dialog makes background inert and blocks direct focus outside it', () => {
  const s = setup(); s.window.openManageModal();
  assert.equal(s.content.hasAttribute('inert'), true);
  assert.equal(s.header.hasAttribute('inert'), true);
  assert.equal(s.main.hasAttribute('inert'), false);
  s.opener.focus(); assert.equal(s.document.activeElement, s.manage.title);
  s.window.closeManageModal();
  assert.equal(s.content.hasAttribute('inert'), false);
  assert.equal(s.header.hasAttribute('inert'), false);
  assert.equal(s.existing.getAttribute('inert'), 'original');
  assert.equal(s.document.activeElement, s.opener);
  assert.equal(s.document.body.style.overflow, 'auto');
});
test('nested review isolates management, restores it on Escape and retains layering', () => {
  const s = setup(); s.window.openManageModal(); s.manage.controls[0].focus();
  s.window.openReviewModal();
  assert.equal(s.manage.hasAttribute('inert'), true);
  assert.equal(s.review.hasAttribute('inert'), false);
  assert.ok(Number(s.review.style.zIndex) > Number(s.manage.style.zIndex));
  s.handlers.keydown({key: 'Escape', preventDefault() {}});
  assert.equal(s.document.activeElement, s.manage.controls[0]);
  assert.equal(s.manage.hasAttribute('inert'), false);
  assert.equal(s.content.hasAttribute('inert'), true);
  s.window.closeManageModal(); assert.equal(s.document.activeElement, s.opener);
});
test('closing a lower dialog keeps the active review isolated and restores original state', () => {
  const s = setup(); s.window.openManageModal(); s.window.openReviewModal();
  s.window.closeManageModal();
  assert.equal(s.document.activeElement, s.review.title);
  assert.equal(s.header.hasAttribute('inert'), true);
  s.window.closeReviewModal();
  assert.equal(s.header.hasAttribute('inert'), false);
  assert.equal(s.existing.getAttribute('inert'), 'original');
});
test('reopening a lower dialog always raises it above the current top', () => {
  const s = setup(); s.window.openManageModal(); s.window.openReviewModal();
  s.window.closeManageModal(); s.window.openManageModal();
  assert.ok(Number(s.manage.style.zIndex) > Number(s.review.style.zIndex));
});
test('removed opener leaves focus on the page instead of a hidden dialog', () => {
  const s = setup(); s.window.openReviewModal(); s.opener.isConnected = false;
  s.window.closeReviewModal();
  assert.equal(s.document.activeElement, s.main);
  assert.equal(s.main.getAttribute('tabindex'), null);
});
