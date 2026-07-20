# DANZA-OS Development Guidance

This branch is the DANZA-OS product source. Keep the product source boundary
separate from generated `APP_BUILD` targets. The packaged payload under
`danzaboss/product/templates/scaffold/` is authoritative for activated
projects.

- Work on one bounded change at a time and write tests before behavior changes.
- Preserve existing CORTEX storage, retrieval, redaction, indexing, graph, UI,
  MCP, aging, and context-budget behavior.
- Treat the packaged constitution as runtime law for activated targets.
- Test activation only in disposable empty and existing Git repositories.
- Do not push, publish, merge, tag, or rewrite history without explicit user
  approval.
- Finish implementation with test evidence, Git status, and a diff summary.
