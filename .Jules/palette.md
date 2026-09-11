## 2025-05-18 - Modal Dialog Accessibility and Toggle State Patterns
**Learning:** Security verification modals and call control toggles require explicit ARIA roles (`role="dialog"`, `aria-modal="true"`, `aria-labelledby`, `aria-describedby`) and toggle state markers (`aria-pressed`) so assistive technologies can properly communicate state transitions during high-urgency call operations.
**Action:** Ensure all overlay security prompts include proper ARIA modal labeling and auto-focus on input fields, and ensure interactive toggle controls carry `aria-pressed`.

## 2025-05-19 - Accessible Single-Select Option Card Groups
**Learning:** In intake and scenario forms, custom clickable card containers acting as single-select options require `role="radiogroup"` with an associated `aria-labelledby`, alongside `role="radio"` and `aria-checked` on each button option so assistive technology users can perceive selection state changes.
**Action:** Always wrap single-select card lists in a `radiogroup` container linked to section headers and mark child options with `role="radio"` and `aria-checked`.
