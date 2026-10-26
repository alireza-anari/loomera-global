# Appointment modal acceptance implementation plan

Goal: reproduce and fix background focus leakage and short-height review clipping in the existing post-booking dialogs.

Authority: the attached Phase 3 execution mandate authorizes implementation, practical tests, one cohesive PR and squash merge after green CI and independent review. No production deployment or earned manual signoff.

Approach: retain the existing modal stack and public functions. Snapshot and restore native inert attributes along the active modal's ancestor path; keep the active dialog above stacked dialogs; constrain the review panel to a scrollable viewport height. Preserve form and translation contracts. Native dialog migration would require broader lifecycle changes and is outside this repair.

- [x] Add unit regressions executing the actual controller; observe failures before production changes.
- [x] Add real Chromium assertions for background focus, nested stacks, restoration and short-height scrolling using production CSS.
- [x] Implement isolation, focus recovery, stack layering and panel scrolling.
- [ ] Run available tests; record environment limitations precisely and use existing CI for independent browser/Django validation.
- [ ] Review complete candidate independently, merge only when exact-head checks pass, verify main.

Review focus: nested modal ancestry, pre-existing inert attributes, non-top close, opener removal, small-height keyboard reachability. All five manual gates remain open until their actual requirements are satisfied.

Execution: 99 Node tests and 10 existing Django tests (minimal local settings) passed. Native fa/en/ar template/script rendering and msgfmt semantic parity passed. Independent reviewer found duplicate Escape listener; regression failed with both listeners, then passed after removal. Browser execution and external CI remain NOT RUN. Publication was rejected by automatic review; no workaround attempted. Remaining unchecked steps require GitHub publication authorization and actual CI.
