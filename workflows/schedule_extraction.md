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
2. For screenshot uploads, preprocess each image before AI scanning:
   - Accept JPG, PNG, and WebP
   - Reject tiny or blurry screenshots
   - Upscale readable screenshots for vision models
   - Increase contrast and sharpen text
   - Convert the final image to compressed JPEG for AI upload
3. Scan with AI provider fallback order:
   - OpenRouter first
   - Gemini second
   - Groq final fallback
4. Extract schedule-like rows only (date/time/site or off-day signals).
5. Normalize events:
   - Ensure date format
   - Keep only date, time, school name
   - Treat blank/off rows as `Day Off`
6. Merge same-date split shifts into one combined daily event for display.
7. Remove duplicates across overlapping inputs.
8. Ensure whole-month coverage by filling missing dates as `Day Off`.
9. Export events to ICS.

## Output
- Clean event list
- ICS file ready for Google/Apple Calendar import

## Guardrails
- Never include non-schedule website text.
- Do not invent dates, times, or school names.
- If confidence is low, prefer explicit `Day Off` over guessed data.
- If a screenshot is too small or blurry, reject it and ask for a clearer zoomed-in capture instead of sending weak input to AI.
