/**
 * Google Apps Script — Sheets Write Proxy
 *
 * HOW TO INSTALL (takes about 3 minutes):
 *
 *  1. Open your Google Sheet in a browser.
 *  2. Click  Extensions → Apps Script
 *  3. Delete all existing code in the editor.
 *  4. Paste this entire file.
 *  5. Click  Save  (disk icon or Ctrl+S).
 *  6. Click  Deploy → New deployment
 *  7. Click the gear icon next to "Select type" → Web app
 *  8. Set:
 *       Description:  Sheets Write Proxy
 *       Execute as:   Me
 *       Who has access: Anyone
 *  9. Click  Deploy → Authorize access → Allow
 * 10. Copy the Web app URL shown (looks like https://script.google.com/macros/s/...)
 * 11. On the Jetson terminal run:
 *       echo 'SHEETS_WEBAPP_URL=<paste-url-here>' >> /home/damon/maxmillion/.env
 *       sudo systemctl restart sheets-agent
 *
 * After that, POST /sync_prices will write live prices into the sheet automatically.
 */

var HOLDINGS_TAB  = "Sheet1";   // name of your main holdings tab
var TRADE_LOG_TAB = "Trade Log"; // name of your trade log tab

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var action = data.action || "";

    if (action === "update_holding") {
      return _updateHolding(data);
    } else if (action === "append_trade") {
      return _appendTrade(data);
    } else {
      return _json({status: "error", detail: "Unknown action: " + action}, 400);
    }
  } catch (err) {
    return _json({status: "error", detail: err.toString()}, 500);
  }
}

// ── GET for quick health check ────────────────────────────────────────────────
function doGet(e) {
  return _json({status: "ok", service: "sheets-write-proxy"});
}

// ── Update or append a holdings row ──────────────────────────────────────────
function _updateHolding(data) {
  var ss      = SpreadsheetApp.getActiveSpreadsheet();
  var tab     = ss.getSheetByName(HOLDINGS_TAB);
  if (!tab) tab = ss.insertSheet(HOLDINGS_TAB);

  var symbol   = (data.symbol   || "").toUpperCase().trim();
  var amount   = data.amount;
  var valueUsd = data.value_usd;

  var lastRow = tab.getLastRow();
  var lastCol = tab.getLastColumn();

  if (lastRow === 0) {
    // Empty sheet — create header
    tab.appendRow(["Symbol", "Amount", "Value USD"]);
    tab.appendRow([symbol, amount, valueUsd || ""]);
    return _json({action: "appended", symbol: symbol, row_index: 2});
  }

  // Read all data to find headers and matching row
  var values  = tab.getRange(1, 1, lastRow, Math.max(lastCol, 3)).getValues();
  var headers = values[0].map(function(h){ return String(h).toLowerCase().trim(); });

  var symIdx = _findCol(headers, ["symbol","coin","ticker","asset","currency","name"]);
  var amtIdx = _findCol(headers, ["amount","qty","quantity","balance","holdings"]);
  var valIdx = _findCol(headers, ["value","current_value","usd_value","total_value","worth","value usd"]);

  if (symIdx === -1) {
    // No symbol column found — just append
    tab.appendRow([symbol, amount, valueUsd || ""]);
    return _json({action: "appended", symbol: symbol, row_index: lastRow + 1});
  }

  // Search for existing row
  var foundRow = -1;
  for (var i = 1; i < values.length; i++) {
    var cell = String(values[i][symIdx]).toUpperCase().trim();
    if (cell === symbol) { foundRow = i + 1; break; }  // 1-based sheet row
  }

  if (foundRow !== -1) {
    // Update in place
    if (amtIdx !== -1) tab.getRange(foundRow, amtIdx + 1).setValue(amount);
    if (valIdx !== -1 && valueUsd !== null && valueUsd !== undefined)
      tab.getRange(foundRow, valIdx + 1).setValue(valueUsd);
    return _json({action: "updated", symbol: symbol, row_index: foundRow});
  } else {
    // Append new row with correct column positions
    var newRow = new Array(Math.max(lastCol, 3)).fill("");
    newRow[symIdx] = symbol;
    if (amtIdx !== -1) newRow[amtIdx] = amount;
    if (valIdx !== -1 && valueUsd !== null && valueUsd !== undefined) newRow[valIdx] = valueUsd;
    tab.appendRow(newRow);
    return _json({action: "appended", symbol: symbol, row_index: lastRow + 1});
  }
}

// ── Append a trade row to Trade Log tab ──────────────────────────────────────
function _appendTrade(data) {
  var ss  = SpreadsheetApp.getActiveSpreadsheet();
  var tab = ss.getSheetByName(TRADE_LOG_TAB);
  if (!tab) tab = ss.insertSheet(TRADE_LOG_TAB);

  if (tab.getLastRow() === 0) {
    tab.appendRow(["Trade ID","Symbol","Side","Qty","Fill Price","PnL Tick","Balance USDT","Timestamp"]);
  }

  tab.appendRow([
    data.trade_id  || "",
    data.symbol    || "",
    (data.side     || "").toUpperCase(),
    data.qty       || 0,
    data.fill_price|| 0,
    data.pnl_tick  || 0,
    data.balance   || 0,
    data.ts        || new Date().toISOString(),
  ]);

  return _json({status: "ok", action: "appended", tab: TRADE_LOG_TAB});
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function _findCol(headers, candidates) {
  for (var i = 0; i < candidates.length; i++) {
    var idx = headers.indexOf(candidates[i]);
    if (idx !== -1) return idx;
  }
  return -1;
}

function _json(obj, code) {
  var output = ContentService.createTextOutput(JSON.stringify(obj))
                             .setMimeType(ContentService.MimeType.JSON);
  return output;
}
