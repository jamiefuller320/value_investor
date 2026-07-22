/* Browser unavailable / bypass watchlist for II-unactionable suggested trades.
 *
 * Names stay on the screen and can keep updating, but are excluded from
 * suggested trades / paper auto-entries until restored. Primary store is
 * localStorage; server-side unavailable_watch.json is a seed/mirror only.
 */

const II_UNAVAILABLE_KEY = "ftse_ii_unavailable_watch_v1";

function loadUnavailableWatch() {
  try {
    const raw = localStorage.getItem(II_UNAVAILABLE_KEY);
    if (!raw) return { items: [] };
    const parsed = JSON.parse(raw);
    const items = Array.isArray(parsed?.items) ? parsed.items : [];
    return {
      items: items.filter((row) => row && row.ticker).map((row) => ({
        ticker: String(row.ticker).toUpperCase(),
        name: row.name || null,
        reason: row.reason || "unavailable_on_ii",
        status: row.status || "watching",
        marked_at: row.marked_at || null,
        updated_at: row.updated_at || null,
        signal: row.signal || null,
        tradable_on_ii: row.tradable_on_ii,
      })),
    };
  } catch {
    return { items: [] };
  }
}

function saveUnavailableWatch(payload) {
  const items = (payload.items || []).map((row) => ({
    ...row,
    ticker: String(row.ticker).toUpperCase(),
  }));
  localStorage.setItem(
    II_UNAVAILABLE_KEY,
    JSON.stringify({ schema_version: 1, updated_at: new Date().toISOString(), items })
  );
}

function unavailableTickerSet() {
  return new Set(loadUnavailableWatch().items.map((row) => String(row.ticker).toUpperCase()));
}

function isUnavailableTicker(ticker) {
  return unavailableTickerSet().has(String(ticker || "").toUpperCase());
}

function markUnavailableTicker(report, reason = "unavailable_on_t212") {
  const ticker = String(report?.ticker || "").toUpperCase();
  if (!ticker) return loadUnavailableWatch();
  const payload = loadUnavailableWatch();
  const now = new Date().toISOString();
  const existing = payload.items.find((row) => row.ticker === ticker);
  if (existing) {
    existing.reason = reason;
    existing.updated_at = now;
    existing.name = report.name || existing.name;
    existing.signal = report.signal || existing.signal;
    existing.tradable_on_ii = report.tradable_on_ii;
    existing.status = "watching";
  } else {
    payload.items.push({
      ticker,
      name: report.name || null,
      reason,
      status: "watching",
      marked_at: now,
      updated_at: now,
      signal: report.signal || null,
      tradable_on_ii: report.tradable_on_ii,
    });
  }
  saveUnavailableWatch(payload);
  return payload;
}

function restoreUnavailableTicker(ticker) {
  const key = String(ticker || "").toUpperCase();
  const payload = loadUnavailableWatch();
  payload.items = payload.items.filter((row) => row.ticker !== key);
  saveUnavailableWatch(payload);
  return payload;
}

/** Merge server seed (from latest.json) into browser list without wiping local marks. */
function mergeServerUnavailableWatch(serverPayload) {
  const local = loadUnavailableWatch();
  const serverItems = Array.isArray(serverPayload?.items) ? serverPayload.items : [];
  if (!serverItems.length) return local;
  const byTicker = new Map(local.items.map((row) => [row.ticker, row]));
  for (const row of serverItems) {
    const ticker = String(row.ticker || "").toUpperCase();
    if (!ticker || byTicker.has(ticker)) continue;
    byTicker.set(ticker, {
      ticker,
      name: row.name || null,
      reason: row.reason || "unavailable_on_ii",
      status: row.status || "watching",
      marked_at: row.marked_at || null,
      updated_at: row.updated_at || null,
      signal: row.signal || null,
      tradable_on_ii: row.tradable_on_ii,
    });
  }
  const merged = { items: [...byTicker.values()] };
  saveUnavailableWatch(merged);
  return merged;
}

function filterActionableCandidates(rows) {
  const blocked = unavailableTickerSet();
  return (rows || []).filter((row) => !blocked.has(String(row.ticker || "").toUpperCase()));
}

window.IIUnavailable = {
  load: loadUnavailableWatch,
  save: saveUnavailableWatch,
  isUnavailable: isUnavailableTicker,
  mark: markUnavailableTicker,
  restore: restoreUnavailableTicker,
  mergeServer: mergeServerUnavailableWatch,
  filterActionable: filterActionableCandidates,
  tickerSet: unavailableTickerSet,
};
