const imageInput = document.querySelector("#imageInput");
const previewGrid = document.querySelector("#previewGrid");
const emptyPreview = document.querySelector("#emptyPreview");
const grokBtn = document.querySelector("#grokBtn");
const ocrProgress = document.querySelector("#ocrProgress");
const scanLoader = document.querySelector("#scanLoader");
const scanLoaderStage = document.querySelector("#scanLoaderStage");
const scanLoaderPct = document.querySelector("#scanLoaderPct");
const scanLoaderFill = document.querySelector("#scanLoaderFill");
const statusEl = document.querySelector("#status");
const usageStatsEl = document.querySelector("#usageStats");
const ocrText = document.querySelector("#ocrText");
const parseBtn = document.querySelector("#parseBtn");
const addRowBtn = document.querySelector("#addRowBtn");
const clearBtn = document.querySelector("#clearBtn");
const sampleBtn = document.querySelector("#sampleBtn");
const downloadBtn = document.querySelector("#downloadBtn");
const googleBtn = document.querySelector("#googleBtn");
const appleBtn = document.querySelector("#appleBtn");
const eventsBody = document.querySelector("#eventsBody");
const exportSummary = document.querySelector("#exportSummary");
const defaultTitle = document.querySelector("#defaultTitle");
const calendarName = document.querySelector("#calendarName");
const monthInput = document.querySelector("#monthInput");

let events = [];
let uploadedImages = [];
let previewUrls = [];
let scanStatuses = [];
let openrouterAvailable = false;
let liveProgressTimer = null;

const today = new Date();
monthInput.value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
calendarName.value = defaultCalendarName();
checkOpenRouterAvailability();
refreshUsageStats();

imageInput.addEventListener("change", () => {
  uploadedImages = Array.from(imageInput.files || []);
  scanStatuses = uploadedImages.map(() => ({ state: "waiting", detail: "Ready" }));
  renderPreviews();
  updateScanModeUI();
  statusEl.textContent = uploadedImages.length
    ? `${uploadedImages.length} screenshot${uploadedImages.length === 1 ? "" : "s"} ready.`
    : "Upload one or more screenshots to begin.";
});

if (grokBtn) grokBtn.addEventListener("click", scanWithGrok);
parseBtn.addEventListener("click", parseEvents);
addRowBtn.addEventListener("click", () => {
  const base = selectedMonth();
  events.push({
    date: `${base.year}-${String(base.month + 1).padStart(2, "0")}-01`,
    allDay: false,
    start: "09:00",
    end: "17:00",
    title: defaultTitle.value.trim() || "Teaching Schedule",
    notes: ""
  });
  events = canonicalizeEvents(events);
  renderEvents();
});

clearBtn.addEventListener("click", () => {
  events = [];
  uploadedImages = [];
  scanStatuses = [];
  imageInput.value = "";
  ocrText.value = "";
  grokBtn.disabled = true;
  renderPreviews();
  renderEvents();
  statusEl.textContent = "Cleared.";
});

sampleBtn.addEventListener("click", () => {
  ocrText.value = [
    "June 2026 Work Schedule",
    "Mon 6/1 10:00-19:00 Kuzuha",
    "Tue 6/2 10:00-19:00 Baika P",
    "Thu 6/4 Day Off",
    "Fri 6/5 10:00-15:00 AIG Nishiizumigaoka",
    "Fri 6/5 15:00-19:00 Ebie"
  ].join("\n");
  monthInput.value = "2026-06";
  calendarName.value = "June 2026 Work Schedule";
  parseEvents();
});

downloadBtn.addEventListener("click", downloadIcs);
appleBtn.addEventListener("click", downloadIcs);
googleBtn.addEventListener("click", openFirstGoogleEvent);

function cleanupOcrText(text) {
  return text
    .replace(/[|]/g, " ")
    .replace(/[–—]/g, "-")
    .replace(/\s+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function improveOcrOnlyText(text) {
  return text
    .replace(/[|]/g, " ")
    .replace(/[–—]/g, "-")
    .replace(/\bO(?=\d)/g, "0")
    .replace(/(?<=\d)O\b/g, "0")
    .replace(/\bl(?=\d)/gi, "1")
    .replace(/\b(\d{1,2})[.](\d{1,2})\b/g, "$1/$2")
    .replace(/\b([AaPp])\s*[Mm]\b/g, (_, m) => `${m.toUpperCase()}M`)
    .replace(/([A-Za-z])(\d{1,2}[\/.-]\d{1,2}\b)/g, "$1\n$2")
    .replace(/(\S)\s+(\d{1,2}[\/.-]\d{1,2}\b)/g, "$1\n$2")
    .replace(/(\d{1,2}[\/.-]\d{1,2})\s*(\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm))/g, "$1 $2")
    .replace(/\s+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

async function checkOpenRouterAvailability() {
  try {
    const response = await fetch("/api/health");
    if (!response.ok) return;
    const health = await response.json();
    openrouterAvailable = Boolean(health.aiConfigured);
    updateScanModeUI();
    if (health.openrouterConfigured && health.groqConfigured) {
      grokBtn.title = "OpenRouter is primary and Groq is ready as fallback.";
    } else if (health.openrouterConfigured) {
      grokBtn.title = "OpenRouter is ready.";
    } else if (health.groqConfigured) {
      grokBtn.title = "Groq fallback is ready.";
    } else {
      grokBtn.title = "Set OPENROUTER_API_KEY or GROQ_API_KEY in .env and run python3 server.py";
    }
  } catch {
    grokBtn.title = "Run python3 server.py to enable AI scanning";
  }
}

async function refreshUsageStats() {
  if (!usageStatsEl) return;
  try {
    const response = await fetch("/api/usage");
    if (!response.ok) return;
    const payload = await response.json();
    const today = payload?.today || {};
    const totals = payload?.totals || {};
    usageStatsEl.textContent = `Usage today: ${Number(today.scans || 0)} scans (${Number(today.images || 0)} images) | Total: ${Number(totals.scans || 0)} scans`;
  } catch {
    // Keep the existing label on connection issues.
  }
}

async function scanWithGrok() {
  if (!uploadedImages.length) return;

  grokBtn.disabled = true;
  setScanLoader(true, "Preparing screenshots", 0);
  ocrProgress.hidden = false;
  ocrProgress.value = 0;
  statusEl.textContent = uploadedImages.length === 1
    ? "Sending screenshot to AI..."
    : `Scanning ${uploadedImages.length} screenshots one by one...`;

  try {
    let failedScans = 0;
    let fallbackUsed = false;
    for (let index = 0; index < uploadedImages.length; index += 1) {
      const file = uploadedImages[index];
      const stepStart = Math.round((index / uploadedImages.length) * 100);
      const stepEnd = Math.round(((index + 1) / uploadedImages.length) * 100);
      const softCap = Math.max(stepStart, stepEnd - 3);
      const currentPct = stepStart;
      setScanLoader(true, `Scanning ${file.name || `screenshot ${index + 1}`}`, currentPct);
      startLiveProgress(stepStart, softCap, 180);
      updateScanStatus(index, "scanning", "Scanning");
      statusEl.textContent = `Scanning screenshot ${index + 1} of ${uploadedImages.length}: ${file.name || "untitled"}`;
      try {
        const payload = await scanSingleScreenshotWithOpenRouter(file);
        fallbackUsed = fallbackUsed || payload.providerUsed === "groq";
        const screenshotEvents = normalizeGrokEvents(payload.events || []);
        events = canonicalizeEvents([...events, ...screenshotEvents]);
        ocrText.value = eventsToText(events);
        renderEvents();
        updateScanStatus(index, "done", `${countWorkEvents(screenshotEvents)} work found`);
      } catch (error) {
        failedScans += 1;
        updateScanStatus(index, "failed", "Failed");
        console.error(error);
      } finally {
        stopLiveProgress();
        const nextPct = stepEnd;
        ocrProgress.value = nextPct;
        setScanLoader(true, `Finished ${index + 1} of ${uploadedImages.length}`, nextPct);
      }
    }

    setScanLoader(true, "Finalizing calendar events", 100);
    events = canonicalizeEvents(events);
    ocrText.value = eventsToText(events);
    renderEvents();
    await refreshUsageStats();
    const providerLabel = fallbackUsed ? " Groq handled the fallback." : "";
    statusEl.textContent = events.length
      ? `Scanned ${uploadedImages.length} screenshot${uploadedImages.length === 1 ? "" : "s"} one by one${failedScans ? `; ${failedScans} failed` : ""}.${providerLabel} Review before exporting.`
      : "The AI did not find events. Try another screenshot or clearer image.";
  } catch (error) {
    const message = String(error.message || "");
    if (message.includes("rate limit") || message.includes("(429)")) {
      statusEl.textContent = "AI rate limit hit. Wait about 1 minute and try again.";
    } else {
      statusEl.textContent = message || "AI scan failed. Try again with a clearer screenshot.";
    }
    console.error(error);
  } finally {
    stopLiveProgress();
    updateScanModeUI();
    setScanLoader(false, "Done", 100);
    ocrProgress.hidden = true;
    ocrProgress.value = 0;
  }
}

function startLiveProgress(startPct, endPct, intervalMs) {
  stopLiveProgress();
  const begin = Math.max(0, Math.min(100, Number(startPct || 0)));
  const end = Math.max(begin, Math.min(100, Number(endPct || begin)));
  let current = begin;
  liveProgressTimer = setInterval(() => {
    if (current >= end) return;
    current += 1;
    ocrProgress.value = current;
    setScanLoader(true, scanLoaderStage?.textContent || "Scanning", current);
  }, Math.max(80, Number(intervalMs || 180)));
}

function stopLiveProgress() {
  if (liveProgressTimer) {
    clearInterval(liveProgressTimer);
    liveProgressTimer = null;
  }
}

function setScanLoader(active, stageText, percent) {
  if (!scanLoader || !scanLoaderStage || !scanLoaderPct || !scanLoaderFill) return;
  scanLoader.hidden = !active;
  if (typeof stageText === "string") scanLoaderStage.textContent = stageText;
  const safePercent = Math.max(0, Math.min(100, Number(percent || 0)));
  scanLoaderPct.textContent = `${safePercent}%`;
  scanLoaderFill.style.width = `${safePercent}%`;
}

function countWorkEvents(items) {
  return items.filter((event) => !/^day\s*off$/i.test(String(event.title || ""))).length;
}

async function scanSingleScreenshotWithOpenRouter(file) {
  const form = new FormData();
  form.append("screenshots", file, file.name);
  form.append("month", monthInput.value);
  form.append("calendarName", calendarName.value.trim() || defaultCalendarName());

  const response = await fetch("/api/openrouter-scan", {
    method: "POST",
    body: form
  });
  const payload = await response.json();

  if (!response.ok) {
    throw new Error(payload.error || `OpenRouter scan failed for ${file.name || "screenshot"}.`);
  }

  return payload;
}

function updateScanModeUI() {
  grokBtn.disabled = uploadedImages.length === 0 || !openrouterAvailable;
}

function normalizeGrokEvents(items) {
  const normalized = items
    .map((item) => {
      let allDay = Boolean(item.allDay);
      let start = String(item.start || "").trim();
      let end = String(item.end || "").trim();
      let title = String(item.title || defaultTitle.value.trim() || "Teaching Schedule").trim();
      const titleLooksOff = title === "-" || title === "—" || title === "–" || /\b(day\s*off|off|holiday|blank|empty|no\s*schedule)\b/i.test(title);
      const timeLooksOff = (start === "-" || start === "—" || start === "–") && (end === "-" || end === "—" || end === "–");

      if (!allDay && (!start || !end)) allDay = true;
      if (titleLooksOff || timeLooksOff) allDay = true;
      if (allDay) {
        start = "";
        end = "";
        if (titleLooksOff || timeLooksOff) title = "Day Off";
      }

      return {
        date: String(item.date || "").trim(),
        allDay,
        start,
        end,
        title,
        notes: String(item.notes || "")
      };
    })
    .filter((item) => item.date && item.title && (item.allDay || (item.start && item.end)));
  return ensureMonthCoverage(canonicalizeEvents(normalized));
}

function canonicalizeEvents(items) {
  const normalized = items.map((event) => ({
    ...event,
    date: String(event.date || "").trim()
  }));
  return combineEventsByDate(dedupeEvents(normalized));
}

function dedupeEvents(items) {
  const seen = new Set();
  const datesWithWork = new Set(items.filter((event) => !event.allDay).map((event) => event.date));
  const unique = [];
  return [...items]
    .sort((a, b) => eventSortKey(a).localeCompare(eventSortKey(b)))
    .filter((event) => {
      if (event.allDay && datesWithWork.has(event.date)) return false;
      const key = [
        event.date,
        event.allDay ? "all-day" : "timed",
        event.start,
        event.end,
        event.title.toLowerCase().replace(/\s+/g, " ").trim()
      ].join("|");
      if (seen.has(key)) return false;
      if (sameTimeDuplicate(unique, event)) return false;
      seen.add(key);
      unique.push(event);
      return true;
    });
}

function sameTimeDuplicate(existingEvents, candidate) {
  if (candidate.allDay) return false;
  return existingEvents.some((event) => {
    if (event.allDay || event.date !== candidate.date) return false;
    if (event.start !== candidate.start || event.end !== candidate.end) return false;
    return titlesAreClose(event.title, candidate.title);
  });
}

function titlesAreClose(left, right) {
  const leftTitle = left.toLowerCase().replace(/\s+/g, " ").trim();
  const rightTitle = right.toLowerCase().replace(/\s+/g, " ").trim();
  return leftTitle === rightTitle;
}

function eventSortKey(event) {
  return `${event.date}|${event.allDay ? "00:00" : event.start}|${event.title.toLowerCase()}`;
}

function eventsToText(items) {
  return items
    .map((event) => {
      const date = formatDisplayDate(event.date);
      const cleanTitle = sanitizeSchoolName(event.title) || "Day Off";
      if (event.allDay) {
        return /^day\s*off$/i.test(cleanTitle) ? `${date} Day Off` : `${date} ${cleanTitle}`;
      }
      return `${date} ${event.start}-${event.end} ${cleanTitle}`;
    })
    .join("\n");
}

function formatDisplayDate(isoDate) {
  const parts = String(isoDate || "").split("-");
  if (parts.length === 3) {
    const month = String(parts[1] || "").padStart(2, "0");
    const day = String(parts[2] || "").padStart(2, "0");
    return `${month}/${day}`;
  }
  const slash = String(isoDate || "").split("/");
  if (slash.length === 2) {
    const month = String(slash[0] || "").padStart(2, "0");
    const day = String(slash[1] || "").padStart(2, "0");
    return `${month}/${day}`;
  }
  return String(isoDate || "");
}

function renderPreviews() {
  for (const url of previewUrls) URL.revokeObjectURL(url);
  previewUrls = [];
  previewGrid.innerHTML = "";

  if (!uploadedImages.length) {
    previewGrid.style.display = "none";
    emptyPreview.style.display = "block";
    return;
  }

  previewGrid.style.display = "grid";
  emptyPreview.style.display = "none";

  uploadedImages.forEach((file, index) => {
    const url = URL.createObjectURL(file);
    previewUrls.push(url);

    const item = document.createElement("figure");
    const status = scanStatuses[index] || { state: "waiting", detail: "Ready" };
    item.className = `preview-item scan-${escapeAttr(status.state)}`;
    item.innerHTML = `
      <img src="${url}" alt="Screenshot ${index + 1} preview">
      <figcaption>
        <span class="preview-name">${escapeHtml(file.name || `Screenshot ${index + 1}`)}</span>
        <span class="scan-badge">${escapeHtml(status.detail)}</span>
      </figcaption>
    `;
    previewGrid.appendChild(item);
  });
}

function updateScanStatus(index, state, detail) {
  scanStatuses[index] = { state, detail };
  renderPreviews();
}

function formatOcrPage(name, text, index) {
  const label = name || `Screenshot ${index + 1}`;
  return [`--- ${label} ---`, cleanupOcrText(text)].join("\n");
}

function parseEvents() {
  const text = cleanupOcrText(ocrText.value);
  const parsed = [];
  let lastDate = null;

  for (const rawLine of text.split(/\n+/)) {
    const line = normalizeLine(rawLine);
    if (!line) continue;
    if (/^---.*---$/.test(line)) continue;

    const time = parseTimeRange(line);
    const explicitDate = parseDateFromLine(line);
    const date = explicitDate || lastDate;
    const allDay = isAllDayLine(line);

    if (explicitDate) {
      lastDate = explicitDate;
    }

    if (!date) {
      continue;
    }

    const title = inferTitle(line, time?.raw || "", date.raw);
    const cleanedTitle = sanitizeSchoolName(title);
    const isDayOffTitle = /^day\s*off$/i.test(cleanedTitle);
    const inferredAllDay = allDay || isDayOffTitle || !time;
    if (!isStrictOcrValid(line, date, time, inferredAllDay, cleanedTitle, Boolean(explicitDate), Boolean(lastDate))) {
      continue;
    }
    parsed.push({
      date: date.iso,
      allDay: inferredAllDay,
      start: inferredAllDay ? "" : (time?.start || ""),
      end: inferredAllDay ? "" : (time?.end || ""),
      title: inferredAllDay && (allDay || isDayOffTitle) ? "Day Off" : (cleanedTitle || defaultTitle.value.trim() || "Teaching Schedule"),
      notes: rawLine.trim()
    });
  }

  events = ensureMonthCoverage(canonicalizeEvents(parsed));
  ocrText.value = eventsToText(events);
  renderEvents();
  statusEl.textContent = parsed.length
    ? `Found ${events.length} event${events.length === 1 ? "" : "s"} after duplicate cleanup.`
    : "No events found. Check the text for dates and time ranges.";
}

function isStrictOcrValid(line, date, time, allDay, title, hasExplicitDate = false, hasContextDate = false) {
  if (!date) return false;
  if (!allDay && !time) return false;
  if (!title || title.trim().length < 2) return false;

  const hasDateInLine = /\b\d{1,2}[\/.-]\d{1,2}(?:[\/.-]\d{2,4})?\b/.test(line) ||
    /\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december)\b/i.test(line) ||
    /\b(?:mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+\d{1,2}\b/i.test(line);

  if (!hasExplicitDate && !hasDateInLine && !hasContextDate) return false;

  if (!allDay) {
    const hasRange = /\b\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)?\s*(?:-|to|~|〜)\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)?\b/.test(line);
    if (!hasRange) return false;
  }

  return true;
}

function sanitizeSchoolName(title) {
  const raw = String(title || "")
    .replace(/\b(?:work|shift|schedule|from|uploaded|pdf|screenshot|room|grade|english|reading|parent|conference|exams?|supervision|teacher|class|lesson|period|homeroom)\b/gi, " ")
    .replace(/\b(?:mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/gi, " ")
    .replace(/\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december)\b/gi, " ")
    .replace(/\b\d{1,2}[\/.-]\d{1,2}(?:[\/.-]\d{2,4})?\b/g, " ")
    .replace(/\b\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)?\s*(?:-|to|~|〜)\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)?\b/g, " ")
    .replace(/[()]/g, " ")
    .replace(/[,:;]/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  if (!raw) return "";
  if (/\b(day\s*off|off|holiday|blank|empty|no\s*schedule)\b/i.test(raw)) return "Day Off";
  return raw;
}

function normalizeLine(line) {
  return line
    .replace(/[Oo](?=\d)/g, "0")
    .replace(/(\d)\s*[:;]\s*(\d)/g, "$1:$2")
    .replace(/\s+/g, " ")
    .trim();
}

function selectedMonth() {
  const [year, month] = monthInput.value.split("-").map(Number);
  return { year, month: month - 1 };
}

function defaultCalendarName() {
  const base = selectedMonth();
  const monthName = new Date(base.year, base.month, 1).toLocaleString("en", { month: "long" });
  return `${monthName} ${base.year} Work Schedule`;
}

function scheduleFileName() {
  const base = selectedMonth();
  const monthName = new Date(base.year, base.month, 1).toLocaleString("en", { month: "long" }).toLowerCase();
  return `${monthName}${base.year}_schedule.ics`;
}

monthInput.addEventListener("change", () => {
  calendarName.value = defaultCalendarName();
});

function parseDateFromLine(line) {
  const base = selectedMonth();
  const monthNames = "jan feb mar apr may jun jul aug sep oct nov dec january february march april june july august september october november december";
  const monthNameRegex = new RegExp(`\\b(${monthNames.split(" ").join("|")})\\.?\\s+(\\d{1,2})(?:st|nd|rd|th)?\\b`, "i");
  const named = line.match(monthNameRegex);
  if (named) {
    const month = monthIndex(named[1]);
    return makeDate(base.year, month, Number(named[2]), named[0]);
  }

  const numeric = line.match(/\b(\d{1,2})[\/.-](\d{1,2})(?:[\/.-](\d{2,4}))?\b/);
  if (numeric) {
    const first = Number(numeric[1]);
    const second = Number(numeric[2]);
    const year = numeric[3] ? normalizeYear(Number(numeric[3])) : base.year;
    const monthFirst = first >= 1 && first <= 12;
    const day = monthFirst ? second : first;
    const month = monthFirst ? first - 1 : second - 1;
    return makeDate(year, month, day, numeric[0]);
  }

  const dayOnly = line.match(/\b(?:mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+(\d{1,2})(?:st|nd|rd|th)?\b/i);
  if (dayOnly) {
    return makeDate(base.year, base.month, Number(dayOnly[1]), dayOnly[0]);
  }

  // Day marker only, e.g. "01" meaning first day of selected month.
  const compactDay = line.match(/^\D*(\d{1,2})\D*$/);
  if (compactDay) {
    const day = Number(compactDay[1]);
    if (day >= 1 && day <= 31) {
      return makeDate(base.year, base.month, day, compactDay[0]);
    }
  }

  return null;
}

function monthIndex(value) {
  const key = value.toLowerCase().slice(0, 3);
  return ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].indexOf(key);
}

function normalizeYear(year) {
  return year < 100 ? 2000 + year : year;
}

function makeDate(year, month, day, raw) {
  if (month < 0 || month > 11 || day < 1 || day > 31) return null;
  const date = new Date(year, month, day);
  if (date.getMonth() !== month || date.getDate() !== day) return null;
  return {
    iso: `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`,
    raw
  };
}

function parseTimeRange(line) {
  const range = line.match(/\b(\d{1,2})(?::?(\d{2}))?\s*([ap]m)?\s*(?:-|to|~|〜)\s*(\d{1,2})(?::?(\d{2}))?\s*([ap]m)?\b/i);
  if (!range) return null;

  const endMeridiem = range[6]?.toLowerCase() || "";
  const startMeridiem = range[3]?.toLowerCase() || inferStartMeridiem(Number(range[1]), Number(range[4]), endMeridiem);
  const start = to24Hour(Number(range[1]), Number(range[2] || 0), startMeridiem);
  const end = to24Hour(Number(range[4]), Number(range[5] || 0), endMeridiem || startMeridiem);

  if (!start || !end) return null;
  return { start, end, raw: range[0] };
}

function isAllDayLine(line) {
  return line.trim() === "-" || /\b(day\s*off|off|holiday|blank|empty|no\s*schedule|休み|休暇)\b/i.test(line);
}

function inferStartMeridiem(startHour, endHour, endMeridiem) {
  if (!endMeridiem) return "";
  if (endMeridiem === "pm" && startHour <= endHour && startHour < 8) return "pm";
  return startHour >= 7 && startHour <= 11 ? "am" : endMeridiem;
}

function to24Hour(hour, minute, meridiem) {
  if (hour > 24 || minute > 59) return null;
  let normalized = hour;
  if (meridiem === "pm" && hour < 12) normalized += 12;
  if (meridiem === "am" && hour === 12) normalized = 0;
  if (!meridiem && hour === 24) normalized = 0;
  if (normalized > 23) return null;
  return `${String(normalized).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function inferTitle(line, timeRaw, dateRaw) {
  let title = line;
  if (timeRaw) title = title.replace(timeRaw, " ");
  if (dateRaw) title = title.replace(dateRaw, " ");
  title = title
    .replace(/\b(mon|tue|wed|thu|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/ig, " ")
    .replace(/\s+/g, " ")
    .trim();
  return title || defaultTitle.value.trim();
}

function renderEvents() {
  eventsBody.innerHTML = "";

  if (!events.length) {
    eventsBody.innerHTML = '<tr class="empty-row"><td colspan="6">Parsed events will appear here.</td></tr>';
  } else {
    events.forEach((event, index) => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td data-label="Date"><input type="date" value="${escapeAttr(event.date)}" data-field="date" data-index="${index}"></td>
        <td data-label="All day"><input type="checkbox" ${event.allDay ? "checked" : ""} data-field="allDay" data-index="${index}"></td>
        <td data-label="Start"><input type="time" value="${escapeAttr(event.start)}" data-field="start" data-index="${index}" ${event.allDay ? "disabled" : ""}></td>
        <td data-label="End"><input type="time" value="${escapeAttr(event.end)}" data-field="end" data-index="${index}" ${event.allDay ? "disabled" : ""}></td>
        <td data-label="Title"><input type="text" value="${escapeAttr(event.title)}" data-field="title" data-index="${index}"></td>
        <td data-label="Remove"><button class="remove-btn" type="button" aria-label="Remove event" data-remove="${index}">x</button></td>
      `;
      eventsBody.appendChild(row);
    });
  }

  updateExportState();
}

eventsBody.addEventListener("input", (event) => {
  const target = event.target;
  const index = Number(target.dataset.index);
  const field = target.dataset.field;
  if (Number.isNaN(index) || !field) return;
  events[index][field] = field === "allDay" ? target.checked : target.value;
  events = canonicalizeEvents(events);
  renderEvents();
  updateExportState();
});

eventsBody.addEventListener("click", (event) => {
  const index = Number(event.target.dataset.remove);
  if (Number.isNaN(index)) return;
  events.splice(index, 1);
  events = canonicalizeEvents(events);
  renderEvents();
});

function updateExportState() {
  const exportReady = validEvents();
  const validCount = exportReady.length;
  downloadBtn.disabled = validCount === 0;
  appleBtn.disabled = validCount === 0;
  googleBtn.disabled = validCount === 0;
  if (!validCount) {
    exportSummary.textContent = "No events ready yet.";
    return;
  }

  const coveredDates = new Set(exportReady.map((event) => event.date)).size;
  const expectedDates = expectedMonthDays();
  const coverage = expectedDates ? `${coveredDates}/${expectedDates} dates covered` : `${coveredDates} dates covered`;
  exportSummary.textContent = `${validCount} event${validCount === 1 ? "" : "s"} ready. ${coverage}.`;
}

function validEvents() {
  const filtered = events.filter((event) => event.date && event.title && (event.allDay || (event.start && event.end)));
  return ensureMonthCoverage(canonicalizeEvents(filtered));
}

function ensureMonthCoverage(items) {
  const [yearStr, monthStr] = String(monthInput.value || "").split("-");
  const year = Number(yearStr);
  const month = Number(monthStr);
  if (!year || !month || month < 1 || month > 12) return items;

  const daysInMonth = new Date(year, month, 0).getDate();
  const byDate = new Map();
  for (const event of items) byDate.set(event.date, true);

  const completed = [...items];
  for (let day = 1; day <= daysInMonth; day += 1) {
    const iso = `${yearStr}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    if (byDate.has(iso)) continue;
    completed.push({
      date: iso,
      allDay: true,
      start: "",
      end: "",
      title: "Day Off",
      notes: "Auto-filled missing date"
    });
  }

  return completed.sort((a, b) => eventSortKey(a).localeCompare(eventSortKey(b)));
}

function expectedMonthDays() {
  const [yearStr, monthStr] = String(monthInput.value || "").split("-");
  const year = Number(yearStr);
  const month = Number(monthStr);
  if (!year || !month || month < 1 || month > 12) return 0;
  return new Date(year, month, 0).getDate();
}

function combineEventsByDate(items) {
  const grouped = new Map();
  for (const event of items) {
    if (!grouped.has(event.date)) grouped.set(event.date, []);
    grouped.get(event.date).push(event);
  }

  const combined = [];
  for (const [date, dayEvents] of grouped.entries()) {
    const timed = dayEvents.filter((event) => !event.allDay);
    const allDaySchools = dayEvents.filter((event) => event.allDay && !/\bday\s*off\b/i.test(String(event.title || "")));
    if (!timed.length) {
      const dayOffs = dayEvents.filter((event) => /\bday\s*off\b/i.test(String(event.title || "")));
      const schools = dayEvents.filter((event) => !/\bday\s*off\b/i.test(String(event.title || "")));
      if (schools.length) {
        const mergedTitle = schools
          .map((event) => String(event.title || "").trim())
          .filter(Boolean)
          .filter((title, index, arr) => arr.indexOf(title) === index)
          .join(" / ");
        combined.push({
          date,
          allDay: true,
          start: "",
          end: "",
          title: mergedTitle || "Teaching Schedule",
          notes: schools.map((event) => event.notes || "").filter(Boolean).join(" | ")
        });
      } else {
        combined.push(dayOffs[0] || dayEvents[0]);
      }
      continue;
    }

    const sortedTimed = [...timed].sort((a, b) => a.start.localeCompare(b.start));
    const mergedTitle = sortedTimed
      .map((event) => event.title.trim())
      .concat(allDaySchools.map((event) => String(event.title || "").trim()))
      .filter(Boolean)
      .filter((title, index, arr) => arr.indexOf(title) === index)
      .join(" / ");

    const mergedNotes = sortedTimed
      .map((event) => event.notes || `${event.start}-${event.end} ${event.title}`)
      .concat(allDaySchools.map((event) => event.notes || event.title || "").filter(Boolean))
      .join(" | ");

    combined.push({
      date,
      allDay: false,
      start: sortedTimed[0].start,
      end: sortedTimed[sortedTimed.length - 1].end,
      title: mergedTitle || sortedTimed[0].title,
      notes: mergedNotes
    });
  }

  return combined.sort((a, b) => eventSortKey(a).localeCompare(eventSortKey(b)));
}

function downloadIcs() {
  const exportEvents = validEvents();
  const ics = buildIcs(exportEvents);
  const blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = scheduleFileName();
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function buildIcs(items) {
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//EscondeKervin Schedule//EN",
    "CALSCALE:GREGORIAN",
    `X-WR-CALNAME:${escapeIcs(calendarName.value.trim() || defaultCalendarName())}`
  ];

  for (const event of items) {
    const eventLines = [
      "BEGIN:VEVENT",
      `UID:${makeUid()}`,
      event.allDay ? `DTSTART;VALUE=DATE:${compactDate(event.date)}` : `DTSTART:${compactDateTime(event.date, event.start)}`,
      event.allDay ? `DTEND;VALUE=DATE:${compactDate(event.date)}` : `DTEND:${compactDateTime(event.date, event.end)}`,
      `SUMMARY:${escapeIcs(event.title)}`,
      "END:VEVENT"
    ];
    lines.push(...eventLines);
  }

  lines.push("END:VCALENDAR");
  return `${lines.join("\r\n")}\r\n`;
}

function compactDateTime(date, time) {
  return `${date.replace(/-/g, "")}T${time.replace(":", "")}00`;
}

function compactDate(date) {
  return date.replace(/-/g, "");
}

function escapeIcs(value) {
  return String(value)
    .replace(/\\/g, "\\\\")
    .replace(/\n/g, "\\n")
    .replace(/,/g, "\\,")
    .replace(/;/g, "\\;");
}

function openFirstGoogleEvent() {
  const event = validEvents()[0];
  if (!event) return;

  const start = googleDate(event.date, event.start);
  const end = googleDate(event.date, event.end);
  const params = new URLSearchParams({
    action: "TEMPLATE",
    text: event.title,
    dates: `${start}/${end}`,
    details: event.notes || "Imported from schedule screenshot.",
    location: ""
  });
  window.open(`https://calendar.google.com/calendar/render?${params.toString()}`, "_blank", "noopener");
}

function googleDate(date, time) {
  return `${date.replace(/-/g, "")}T${time.replace(":", "")}00`;
}

function makeUid() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeAttr(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

renderEvents();
