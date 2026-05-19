/**
 * DOM test harness for siaDC09.js diagnostic rendering functions.
 *
 * Loads the diagnostic section of siaDC09.js (lines 700+) into a jsdom window
 * with jQuery, then runs the test scenarios passed as JSON via argv and prints
 * results as a JSON array to stdout.
 *
 * Usage:
 *   node js_dom_harness.js '<scenarios_json>'
 *
 * Each scenario is: { "fn": "<function_name>", "args": [...], "query": "<css_selector>",
 *                     "attr": "<attribute>"|null, "prop": "<property>"|null }
 * Result per scenario: { "ok": true, "html": "...", "text": "...", "style": {...},
 *                        "attr": "...", "count": N, "error": null }
 */

'use strict'

const { JSDOM } = require('./../../node_modules/jsdom')
const fs = require('fs')
const path = require('path')

const PROJECT_ROOT = path.resolve(__dirname, '../..')

// ── Build DOM ─────────────────────────────────────────────────────────────────

const dom = new JSDOM(`<!DOCTYPE html><html><body>
  <ul class="nav nav-tabs">
    <li id="siaDC09_diagnosticTabLi" style="display:none;"><a href="#diagnosticTab">Diag</a></li>
  </ul>
  <div id="diagnosticTab"></div>
  <div id="siaDC09_badgeDot"></div>
  <div id="siaDC09_badgeLabel"></div>
  <div id="siaDC09_errorsList"></div>
  <div id="siaDC09_inspectorList"></div>
  <div id="div_alert"></div>
</body></html>`, { runScripts: 'dangerously' })

const window = dom.window
const document = window.document

// Load jQuery
const jQuerySrc = fs.readFileSync(
  path.join(PROJECT_ROOT, 'node_modules/jquery/dist/jquery.js'), 'utf8'
)
window.eval(jQuerySrc)
const $ = window.$

// Stub unavailable jQuery plugins / Jeedom APIs
$.fn.sortable = function() { return this }
$.fn.showAlert = function() { return this }
$.ajax = function() {}
window.jeedomUtils = { saveEquipment: function() {} }

// Load diagnostic section of siaDC09.js (skip lines 0-699 which need jQuery UI)
const allLines = fs.readFileSync(
  path.join(PROJECT_ROOT, 'desktop/js/siaDC09.js'), 'utf8'
).split('\n')
const diagSection = allLines.slice(700).join('\n')
window.eval(diagSection)

// ── Test runner ───────────────────────────────────────────────────────────────

function resetDOM() {
  document.getElementById('siaDC09_diagnosticTabLi').style.display = 'none'
  document.getElementById('siaDC09_badgeDot').style.color = ''
  document.getElementById('siaDC09_badgeDot').style.cssText = ''
  document.getElementById('siaDC09_badgeLabel').textContent = ''
  document.getElementById('siaDC09_errorsList').innerHTML = ''
  document.getElementById('siaDC09_inspectorList').innerHTML = ''
  window._siaDC09_decodeCache = {}
}

function getStyleObj(el) {
  const styles = {}
  for (const prop of ['color', 'display', 'background', 'font-weight']) {
    const v = el.style.getPropertyValue(prop)
    if (v) styles[prop] = v
  }
  return styles
}

function runScenario(scenario) {
  resetDOM()
  const result = { ok: false, html: null, text: null, style: null, attr: null, count: null,
                   value: null, error: null }
  try {
    const fn = window[scenario.fn]
    if (!fn) throw new Error(`function ${scenario.fn} not found in window`)

    let returnValue
    if (scenario.fn === 'siaDC09_buildHexButtons' || scenario.fn === 'siaDC09_buildFieldTable') {
      // These return a jQuery object — append to inspectorList for querying
      const $el = fn.apply(window, scenario.args || [])
      window.$('#siaDC09_inspectorList').append($el)
      returnValue = null
    } else if (scenario.fn === 'siaDC09_renderFrameDetail') {
      // Needs a $detail div — use inspectorList
      const $detail = window.$('<div class="sia-msg-detail">')
      window.$('#siaDC09_inspectorList').append($detail)
      fn.apply(window, [$detail].concat(scenario.args || []))
      returnValue = null
    } else {
      returnValue = fn.apply(window, scenario.args || [])
    }

    const query = scenario.query
    if (query) {
      const el = document.querySelector(query)
      if (el) {
        result.html = el.innerHTML
        result.outerHTML = el.outerHTML
        result.text = el.textContent.trim()
        result.style = getStyleObj(el)
        if (scenario.attr) result.attr = el.getAttribute(scenario.attr)
        if (scenario.prop) result.count = document.querySelectorAll(scenario.prop).length
      } else {
        result.count = 0
      }
    }
    if (scenario.count_query) {
      result.count = document.querySelectorAll(scenario.count_query).length
    }
    if (scenario.fn === 'siaDC09_formatTimestamp') {
      result.value = returnValue
    }
    if (scenario.cache_key_test) {
      // Test that two frames with same requestHex but different responseHex get distinct cache entries
      const cache = window._siaDC09_decodeCache
      const decoded = { id_token: 'SIA-DCS', crc_valid: true, crc_received: 'ABCD',
                        crc_computed: 'ABCD', sequence: 1, account: '1234',
                        account_prefix: 'L', receiver_prefix: '', data_raw: '#1234|0000',
                        length_declared: 30, length_actual: 30, crc_format: 'SIA',
                        encrypted: false, extended_fields: {} }
      const $list = window.$('#siaDC09_inspectorList').empty()
      const $detail1 = window.$('<div class="sia-msg-detail">')
      const $detail2 = window.$('<div class="sia-msg-detail">')
      $list.append($detail1).append($detail2)
      const msg = { dialog_type: 'supervision', routine: 1, timestamp: '2026-01-01T12:00:00Z',
                    elapsed_ms: 100, request_hex: 'AABB', response_hex: 'CC11' }
      const msg2 = { dialog_type: 'supervision', routine: 1, timestamp: '2026-01-01T12:01:00Z',
                     elapsed_ms: 200, request_hex: 'AABB', response_hex: 'DD22' }
      // Simulate cache writes with the new composite key
      const key1 = 'AABB|CC11'
      const key2 = 'AABB|DD22'
      cache[key1] = decoded
      cache[key2] = { ...decoded, sequence: 2 }
      result.value = {
        key1_exists: key1 in cache,
        key2_exists: key2 in cache,
        keys_distinct: key1 !== key2,
        old_key_absent: !('AABB' in cache),
      }
    }
    result.ok = true
  } catch (e) {
    result.error = e.message
  }
  return result
}

// ── Main ──────────────────────────────────────────────────────────────────────

const scenarios = JSON.parse(process.argv[2] || '[]')
const results = scenarios.map(runScenario)
process.stdout.write(JSON.stringify(results) + '\n')
