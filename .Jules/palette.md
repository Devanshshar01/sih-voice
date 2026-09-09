## 2025-05-18 - Modal Dialog Accessibility and Toggle State Patterns
**Learning:** Security verification modals and call control toggles require explicit ARIA roles (`role="dialog"`, `aria-modal="true"`, `aria-labelledby`, `aria-describedby`) and toggle state markers (`aria-pressed`) so assistive technologies can properly communicate state transitions during high-urgency call operations.
**Action:** Ensure all overlay security prompts include proper ARIA modal labeling and auto-focus on input fields, and ensure interactive toggle controls carry `aria-pressed`.
