# Workflow: Monthly Schedule Extraction

## Objective
Convert teacher schedule input into clean monthly events for calendar export.

## Inputs
- `month` in `YYYY-MM`
- One of:
  - Screenshot uploads
  - Public URL
  - Pasted website text (recommended for login-protected pages)

## Tool Sequence
1. Validate input source and month.
2. Extract schedule-like rows only (date/time/site or off-day signals).
3. Normalize events:
   - Ensure date format
   - Keep only date, time, school name
   - Treat blank/off rows as `Day Off`
4. Merge same-date split shifts into one combined daily event for display.
5. Remove duplicates across overlapping inputs.
6. Ensure whole-month coverage by filling missing dates as `Day Off`.
7. Export events to ICS.

## Output
- Clean event list
- ICS file ready for Google/Apple Calendar import

## Guardrails
- Never include non-schedule website text.
- Do not invent dates, times, or school names.
- If confidence is low, prefer explicit `Day Off` over guessed data.
