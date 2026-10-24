/* Phase 3: data-only bridge from Django's compiled gettext catalogs.
 * This file must load after json_script and before feedback.js/app.js. */
(function () {
  "use strict";
  const element = document.getElementById("loomera-interactive-messages");
  if (!element) return;
  let payload;
  try {
    payload = JSON.parse(element.textContent || "{}");
  } catch (_) {
    return;
  }
  if (!payload || !["fa", "en", "ar"].includes(payload.language)
      || !payload.messages || typeof payload.messages !== "object"
      || Array.isArray(payload.messages)) return;

  const messages = Object.create(null);
  for (const [key, value] of Object.entries(payload.messages)) {
    if (!/^(feedback|validation|submit|password|booking)\.[a-z_.]+$/.test(key)) continue;
    if (typeof value === "string" && value.length <= 300) messages[key] = value;
  }
  Object.freeze(messages);
  // Booking labels are UI display copy, not acceptable server flash bodies.
  // Keep the existing reviewed feedback/validation trust boundary unchanged.
  const approved = new Set(Object.entries(messages)
    .filter(([key]) => !key.startsWith("booking."))
    .map(([, value]) => value));

  const text = (key, fallback = "") => (
    Object.prototype.hasOwnProperty.call(messages, key) ? messages[key] : fallback
  );
  const format = (key, parameters, fallback = "") => text(key, fallback).replace(
    /\{(min|max)\}/g,
    (_, name) => Object.prototype.hasOwnProperty.call(parameters || {}, name)
      ? String(parameters[name])
      : ""
  );

  window.LoomeraI18n = Object.freeze({
    language: payload.language,
    text,
    format,
    isTrustedMessage: (value) => typeof value === "string" && approved.has(value.trim()),
  });
})();
