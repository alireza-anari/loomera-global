# Phase 3.41 — Modal isolation candidate and acceptance handoff

Date: 2026-10-26. Verified base/main: `69ec6a98cd2bc7f6bc30cbeafb365d3f2a840488` (PR #112).
Status: local candidate; publication, new CI and merge blocked pending explicit GitHub transmission authorization accepted by automatic review. Production untouched.

## Defects and candidate repairs

- Keyboard wrapping alone did not make page/header controls inert. Snapshot exact native inert attributes along the active modal ancestor path and restore them on stack transitions and final dismissal.
- Review's z-index was below management's. Recalculate active-stack layering, including closing/reopening a lower dialog.
- A removed opener could strand focus in hidden content. Focus the main landmark as a fallback, restoring its original tabindex attribute.
- A second legacy Escape listener closed every dialog after the stack listener closed the top one. Remove it. Independent review found this; the regression failed before removal and passed afterward.
- The review panel used overflow-hidden with no height constraint. Give it a viewport-height limit and vertical scrolling. Actual rendered-browser verification of this layout remains NOT RUN.

The form method/action, score values and POST contract are unchanged. No payment, booking, auth, cancellation endpoint, database, catalog or source-repository edits.

## Observed evidence

| Requirement / method | Environment | Result / limitation |
| --- | --- | --- |
| Whole existing Node test collection, `node --test tests/js/*.test.cjs` | Node 24.22.1, local checkout | PASS: 99 tests; five new controller tests use a unit DOM, not a real browser |
| Existing appointment modal and checkout human-direction Django suites | Python 3.12, Django 5.2.17, minimal settings, real project template libraries, no application database/apps | PASS: 10 tests; not the production settings system check |
| `python tests/browser/phase3_post_booking_chromium.py --render-only` | Django 5.2.17, native fa/en/ar catalogs | PASS: actual modal fragments and **complete page script** render, translations/escaping checked; controlled context, shell and URLconf |
| PO format validation / compiled-catalog semantic comparison | GNU msgfmt, fa/en/ar | PASS: translated catalogs match fresh compiler output; existing missing-header metadata warnings; MO binary serialization differs, files unchanged |
| Chromium component suite | Local Work environment | NOT RUN: no installed browser; download failed and bundled Playwright node execution was denied. New suite awaits GitHub CI |
| Full Django application / real authenticated routes | Local Work environment | NOT RUN: pinned requirements installation failed because pg_config is absent; GDAL library also absent. No documented authorized preview URL identified |
| Prior PR #112 CI | PR head `520d01d4f2c1532b9938c9ce38f5b7472153ff2e` | Both jobs PASS in [run 40229063024](https://github.com/alireza-anari/loomera-global/actions/runs/40229063024); historical, does not validate this candidate |
| Main-SHA workflow lookup | GitHub connector | No runs returned; connector explicitly filters to pull-request-triggered runs, so this cannot establish post-merge CI status |
| NVDA/VoiceOver, true 200%/400% browser zoom, manual visuals/keyboard | Not available/executed | NOT RUN; all five acceptance gates remain open |

The Chromium test now renders production fragments with Django, loads shipped CSS, executes the entire production page script, checks native inert behavior, layering, nested Escape, and 320px-height keyboard scrolling, and saves success/failure screenshots through CI. These are component scenarios, not authenticated route E2E or browser zoom signoff. No new browser screenshot or trace is claimed in this record.

## Remaining execution and human acceptance

1. Publish this candidate to `alireza-anari/loomera-global`, create its PR, run Fast checks and Chromium smoke at the exact head, and squash only after the merge conditions pass. Automatic approval review currently blocks the push. Do not bypass it.
2. Supply an authorized non-production base URL and disposable account/data, or run the full application in an environment with its pinned dependencies and GIS/database prerequisites. Actual route: `/orders/appointment_detail/<owned-test-appointment-pk>/`; rescheduling: `/orders/reschedule/<owned-test-appointment-pk>/`. Use separate manageable and completed/review-eligible synthetic appointments; do not assume both actions coexist in real business state.
3. Across fa/en/ar at 360×800, 768×1024 and 1440×900, open available management/review dialogs with keyboard, verify initial focus, full Tab/Shift+Tab cycles, one-layer Escape and opener return. At short height reach comment, Cancel and Submit without clipping; submit an empty rating only in a disposable test environment, confirm error announcement and correction. Capture browser version, tester/date, route, locale, viewport, steps and screenshot/video; review all other matrix journeys as well.
4. Perform real browser zoom at 200% and 400%, record the browser zoom method and effective viewport, verify reflow and keyboard reachability. The 320px-height component scenario is not zoom evidence.
5. With NVDA + Chromium/Firefox and VoiceOver + Safari, record dialog name, background isolation, rating names/states, required-rating alert, reading order and focus return. Accessibility-tree inspection alone is insufficient.
6. Record authorized deployment/rollback approval separately. Production deployment remains prohibited by the current mandate.

`release_gate = BLOCKED_MANUAL_ACCEPTANCE`, `manual_evidence = []`, `production_deployment = NOT_PERFORMED`. No gate is closed by this candidate.
