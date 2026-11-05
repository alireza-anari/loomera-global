# Phase 4.3d — Public SEO Metadata Localization

Status: **implementation candidate**. Exact-head GitHub CI and independent review required before merge. Phase 3 still has `BLOCKED_MANUAL_ACCEPTANCE`, and no Production deployment is authorized.

## Scope

- Native Django gettext on the **shared generic fallback** description and OG/Twitter description, while leaving the shared title and OG/Twitter title driven by the deployment brand. Preserve exact default Persian output, including punctuation.
- Localize public homepage title (using the previously reviewed `Beauty, made simpler` translation and Persian/other-locale brand selection), salon discovery title, and service-directory **fallback** title and description.
- Localize public magazine title and meta description, with Persian `deployment_brand.display_name_fa` but buyer-configured `deployment_brand.display_name` on English and Arabic requests.
- Localize the expert profile description while safely interpolating merchant-owned professional and salon names without translating them.
- Eight reviewed new strings and one reused existing key are registered in `PHASE4_3D_MESSAGE_REVIEW.json`. All three native PO/MO catalogs increase from 896 to 904 entries, preserving every existing key/value pair exactly.
- Add exact locale/brand output, interpolation escaping, merchant SEO authority, template compilation and compiled PO/MO parity tests. Existing older catalog-count tests are updated to the exact compiled count.

## Non-goals and invariants

- Explicitly **do not** rewrite `salon.effective_seo_title`, `salon.effective_seo_description`, `service.effective_seo_title`, `service.effective_seo_description`, or `selected_group.effective_seo_*`, which are domain/merchant-authored.
- **Do not** treat Help Center/legal/article content as translated; those require their own locale and jurisdiction ownership scope.
- **No changes** to SEO URL/canonical, robots/noindex, hreflang, sitemap, structured data, media, pricing, booking/checkout, search semantics, database/migrations, timezone or calendar.
- The existing canonical/social image/OG locale policy is unchanged. Page-specific OG/Twitter overrides beyond existing overrides are not claimed.
- Original Persian metadata is preserved on migrated surface titles/descriptions; brand values are selected via deployment configuration and HTML-escaped.
- Source repository `alireza-anari/loomera` is read-only. No Production deployment or manual signoff is performed.

## Merge requirements

1. Independently verify all 896 compiled baseline translations remain identical in fa/en/ar and exactly eight new catalog keys match the reviewed ledger.
2. GitHub CI Fast checks and Chromium keyboard smoke must succeed on the exact PR head, including new Phase 4.3d test step and existing production hygiene.
3. Compare the PR diff against pinned main and explicitly inspect the SEO templates, all catalog artifacts and tests.
4. Guarded `expected_head_sha` squash merge only after green. Verify post-merge CI on final main SHA.

Phase 3 manual visual/browser, real keyboard, true 400% zoom, NVDA/VoiceOver and release authorization remain outstanding and must not be represented as complete.
