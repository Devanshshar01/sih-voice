## 2025-05-18 - Modal Dialog Accessibility and Toggle State Patterns
**Learning:** Security verification modals and call control toggles require explicit ARIA roles (`role="dialog"`, `aria-modal="true"`, `aria-labelledby`, `aria-describedby`) and toggle state markers (`aria-pressed`) so assistive technologies can properly communicate state transitions during high-urgency call operations.
**Action:** Ensure all overlay security prompts include proper ARIA modal labeling and auto-focus on input fields, and ensure interactive toggle controls carry `aria-pressed`.

## 2025-05-19 - Custom Option Card Radio Group Semantics
**Learning:** Custom button groups functioning as single-choice option pickers (e.g., monitoring mode selection) require explicit `role="radiogroup"`, `aria-labelledby`, `role="radio"`, and `aria-checked` attributes so screen reader users can perceive the selection context and active state.
**Action:** Whenever custom cards or buttons are used as single-selection radio alternatives, wrap the container with `role="radiogroup"` and mark individual choices with `role="radio"` and `aria-checked`.
