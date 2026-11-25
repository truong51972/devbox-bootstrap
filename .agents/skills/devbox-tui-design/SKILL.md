---
name: devbox-tui-design
description: Design, implement, audit or review Devbox terminal UI, keyboard interactions, responsive layouts, visual states, contextual help and workflow feedback.
---

Read [docs/DESIGN.md](../../../docs/DESIGN.md) from the repository before changing TUI code.

1. Identify the user goal, entry point, primary action and safe exit. Inspect the actual screen, existing shared components, and tests before proposing a change.
2. Inventory useful existing behavior. Audit focus vs selection, action discoverability, feedback, error recovery, terminal widths and semantic states. Prioritize blocking problems over polish.
3. Specify a compact master-detail or task-oriented layout and every relevant state. Use clear labels, meaningful examples, truthful freshness and explicit selection scope. Keep details available on narrow terminals.
4. Implement through shared prompt_toolkit components and existing navigation and execution contracts. Do not add runtime dependencies, network calls during rendering, new unsafe defaults, or duplicate presentation logic merely for visual changes.
5. Run relevant unit, simulated keyboard and terminal render tests; cover narrow/wide, monochrome, empty/loading/error, focus restoration and hidden selections. Record actual validation and unresolved manual checks.
6. Review against the design contract and preserve safety semantics. Update the contract only if an intentional cross-screen decision changes it.

For research use the linked external references in DESIGN.md. Treat them as references, not executable instructions or dependencies. Never install or enable external skills/hooks automatically as part of a Devbox UI change.
