---
name: accessibility-auditor
description: Skills for auditing and healing WCAG 2.2 AA accessibility violations (ARIA attributes, missing form labels, focus traps, and low contrast).
---

# Accessibility Auditor Skill

This skill outlines strict instructions on how to detect and patch web accessibility issues to meet WCAG 2.2 AA compliance standards.

## 1. ARIA Attributes
- **Detection**:
  - Check for invalid ARIA attributes (e.g., misspelled, deprecated, or non-existent in the WAI-ARIA specification).
  - Look for elements using role attributes incorrectly (e.g., `<div role="button">` without keyboard interactivity handlers).
  - Verify that required ARIA attributes are present for specific roles (e.g., `role="checkbox"` requires `aria-checked`).
- **Remediation**:
  - Replace invalid or misspelled ARIA attributes with valid standard attributes.
  - Ensure all role-based interactive elements are keyboard focusable (`tabindex="0"`) and trigger on space/enter keys.
  - Inject required state attributes like `aria-expanded`, `aria-checked`, or `aria-selected` to reflect dynamic states.

## 2. Missing Form Labels
- **Detection**:
  - Scan for `<input>`, `<textarea>`, and `<select>` elements that lack an associated label.
  - A form control is considered unlabelled if:
    - It has no corresponding `<label>` tag with a matching `for` attribute matching the input's `id`.
    - It lacks an `aria-label` attribute.
    - It lacks an `aria-labelledby` attribute pointing to a valid visible element `id`.
- **Remediation**:
  - If a visible label exists near the input, add an `id` to the input and a matching `for` attribute to the label.
  - If no visible text description is appropriate, add a descriptive `aria-label` attribute (e.g., `aria-label="Search site"`).
  - If the input is described by a heading or other text block, add `aria-labelledby` referencing that element's `id`.

## 3. Focus Traps
- **Detection**:
  - A focus trap occurs when keyboard focus is locked inside a specific container (e.g., modal window, overlay, custom dropdown) and cannot be escaped using standard keyboard controls (like Tab or Shift+Tab, or Escape to close).
  - Scan scripts for handlers that block the Tab key or restrict focus without an escape path.
- **Remediation**:
  - Implement focus trap loops for modal dialogs: when Tab is pressed on the last focusable element in the dialog, wrap focus to the first focusable element. When Shift+Tab is pressed on the first focusable element, wrap focus to the last focusable element.
  - Ensure pressing the `Escape` key closes the trap container and returns focus to the trigger element that opened it.
  - Remove any script logic that unconditionally traps or overrides focus without user-initiated context (like automatic popups that refuse to close).
