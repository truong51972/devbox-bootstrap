# Devbox TUI design contract

Devbox is a keyboard-first local developer workstation manager, not a graphical dashboard. Optimize for clarity, information density, and safe execution rather than decoration. Preserve prompt_toolkit, existing operation safeguards and fast background discovery.

## Visual language

- Use the terminal default foreground for normal text; ANSI colors are semantic roles, not fixed RGB values. Provide monochrome equivalents and text labels.
- Success (green): installed/current/completed. Attention (yellow): updates, partial, unknown/unverified, manual action. Failure (red): missing or failed. Active (cyan): checking/running. Neutral: unavailable/not applicable. Focus and selection remain independent.
- The header identifies location, the footer shows available keys, and the notice area explains the last outcome. Use concise sentence-case labels and avoid redundant headings.
- Right-align comparable states; use terminal cell widths, not Unicode character counts. Preserve full labels and status in the inspect view. Never use color as the sole carrier of information.
- At 94+ columns retain the stable half-width master-detail split. At intermediate widths use a compact preview if height permits; small terminals show the list and offer an inspect screen. Do not create a new layout on each redraw.
- Keep raw logs distinct from structured information. Prefer formatted fragments or typed results for new screens. The existing semantic lexer is a compatibility bridge, not a new presentation API.

## Interaction

| Key | Contract |
| --- | --- |
| Enter | Open, inspect, run a read-only action, or review; never bypass required confirmation |
| Space | Toggle selection; disabled rows cannot be selected |
| Esc | Back/cancel/clear active filter, restoring origin and focus |
| Up/Down, j/k | Navigate lists |
| / | Filter visible list |
| A | Explicitly named preset (all filtered, recommended, or safe); show scope |
| N | Clear selection, including hidden selection |
| U / C | Verified updates / retryable checks in resource workspaces |
| R | Refresh current data |
| I | Full details |
| X | Related actions |
| ? / F1 | Contextual help; F1 also works while editing |
| Ctrl+K | Catalog search where supported |
| Tab | Move between focusable fields or panels where supported |

The binding, footer and help must agree. Avoid introducing a second shortcut for the same purpose unless it has an explicit compatibility rationale. Never advertise an unavailable action as enabled. Preserve selected items hidden by a filter where intended and disclose their count before review.

## Screen patterns

Home/Info: concise task groups, current source status, repository, environment.
Resource manager: summary with freshness, grouped list, independent installation/update states, detail with evidence and next action.
Action catalog: goal-oriented labels, examples, prerequisites and limitations.
Input: explicit field labels, meaningful defaults, validation and recovery.
Read-only results: outcome summary, structured table, details, related actions and raw output where available.
Cleaner: safe preset vs manual risk, exact selection, estimates not promises.
Confirmation: exact reviewed targets, impact, dependencies, consent; destructive or privileged options remain off by default.
Execution: actual completed steps, progress and bounded logs; do not invent percentages or detach package transactions.
Result/history: per-target outcome, failures and next steps; distinguish preview from applied changes.
Settings: current value, default and override precedence.

## Verification matrix

Test 58, 80, 94, 120 and 160 columns, short height and live resize, ANSI and mono, light and dark terminal palettes, CJK/wide and combining characters, filtered selections and focus restoration. Exercise empty/loading/partial/error/unsupported states, slow probes, confirmation cancellation and result return. Use existing prompt_toolkit simulated input and Screen render tests; do not run real package operations in CI. For visual changes include representative terminal captures or state explicitly if unavailable.

## References

- [tui-design](https://github.com/diegomarino/tui-design): evidence-based terminal design and review.
- [Monospace Design TUI](https://coreyt.github.io/monospace-design-tui/standard/): terminal layout and interaction patterns.
- [GitHub TUIKit](https://github.com/github/TUIKit/blob/main/docs/foundations.md): focus, accessibility and component foundations.
- [Impeccable](https://github.com/pbakaus/impeccable): critique, clarity and design documentation; adapt only terminal-relevant ideas.

This is a Devbox-specific contract, not an assertion of compliance with any external standard.
