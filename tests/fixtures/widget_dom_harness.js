/**
 * DOM test harness for the siaDC09 dashboard widget template.
 *
 * Loads core/template/dashboard/siaDC09.html into a jsdom window (with #placeholders#
 * substituted), runs its inline <script> "dangerously", then drives live-refresh
 * scenarios and reports the resulting DOM state — badge class, label/event text,
 * badge title — so tests assert on real behaviour, not keyword presence.
 *
 * Usage:
 *   node widget_dom_harness.js '<scenarios_json>'
 *
 * Each scenario:
 *   {
 *     "template": "dashboard" | "mobile",     // which template file to load
 *     "placeholders": { "<key>": "<value>" }, // #key# substitutions
 *     "byId": { "staleSeconds": N } | null,    // supervision_state collectDate = now - N sec
 *     "now": <epoch_ms>,                       // fixed Date.now() for deterministic stale calc
 *     "actions": [ { "type": "pushState"|"pushLabel"|"pushEvent", "value": "..." } ]
 *   }
 *
 * Result per scenario:
 *   { "ok": true, "badgeClass": "...", "labelText": "...", "eventText": "...",
 *     "title": "...", "error": null }
 *
 * A pushed value is written into the matching cmdValue span exactly the way Jeedom's
 * native cmd::update handler mutates it (span.innerHTML = value), so the widget's
 * MutationObserver sees the same event it would in production.
 */

'use strict'

const { JSDOM } = require('./../../node_modules/jsdom')
const fs = require('fs')
const path = require('path')

const PROJECT_ROOT = path.resolve(__dirname, '../..')

const DEFAULT_PLACEHOLDERS = {
  id: '42',
  version: 'dashboard',
  name: 'siaDC09',
  eqLink: '#',
  supervision_interval: '60',
  badge_class: 'text-success',
  supervision_label: 'OK',
  event_label: 'Inactif',
  supervision_state_value: '2',
  supervision_state_id: '101',
  supervision_label_id: '102',
  event_label_id: '103',
  stale_label: 'Données non disponibles',
  stale_tooltip_prefix: 'Dernière mise à jour il y a',
}

function renderTemplate(which, placeholders) {
  const file = which === 'mobile'
    ? 'core/template/mobile/siaDC09.html'
    : 'core/template/dashboard/siaDC09.html'
  let html = fs.readFileSync(path.join(PROJECT_ROOT, file), 'utf8')
  const merged = Object.assign({}, DEFAULT_PLACEHOLDERS, placeholders || {})
  for (const key of Object.keys(merged)) {
    html = html.split('#' + key + '#').join(String(merged[key]))
  }
  return html
}

// Flush pending microtasks so jsdom MutationObserver callbacks run.
function flush() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

async function runScenario(scenario) {
  const result = { ok: false, badgeClass: null, labelText: null, eventText: null,
                   title: null, error: null }
  try {
    const body = renderTemplate(scenario.template, scenario.placeholders)
    const dom = new JSDOM(`<!DOCTYPE html><html><body>${body}</body></html>`,
                          { runScripts: 'outside-only' })
    const window = dom.window
    const document = window.document

    // Deterministic clock for the stale calculation.
    if (typeof scenario.now === 'number') {
      const fixed = scenario.now
      const RealDate = window.Date
      function FakeDate(...args) {
        if (args.length === 0) return new RealDate(fixed)
        return new RealDate(...args)
      }
      FakeDate.now = () => fixed
      FakeDate.prototype = RealDate.prototype
      FakeDate.parse = RealDate.parse
      FakeDate.UTC = RealDate.UTC
      window.Date = FakeDate
    }

    // Build a collectDate string N seconds before the fixed clock, formatted in
    // local time as "YYYY-MM-DD HH:MM:SS" so the widget's own local-time parse
    // round-trips to the same instant regardless of the runner's timezone.
    function collectDateString(staleSeconds) {
      const base = (typeof scenario.now === 'number') ? scenario.now : Date.now()
      const d = new Date(base - staleSeconds * 1000)  // Node's real global Date
      const p = (n) => String(n).padStart(2, '0')
      return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
        ' ' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds())
    }

    // Stub Jeedom's eqLogic.byId used by the one-shot stale check.
    window.jeedom = {
      eqLogic: {
        byId: function (opts) {
          if (!scenario.byId) return
          const cmd = {
            logicalId: 'supervision_state',
            collectDate: collectDateString(scenario.byId.staleSeconds),
          }
          if (opts && typeof opts.success === 'function') {
            opts.success({ cmd: [cmd] })
          }
        },
      },
    }
    window.jeedomUtils = { loadPage: function () {} }

    // Execute every inline <script> in document order.
    const scripts = document.querySelectorAll('script')
    for (let i = 0; i < scripts.length; i++) {
      window.eval(scripts[i].textContent)
    }
    await flush()

    // Apply live-push actions the way Jeedom mutates bound cmdValue spans.
    const idMap = {
      pushState: (scenario.placeholders && scenario.placeholders.supervision_state_id)
        || DEFAULT_PLACEHOLDERS.supervision_state_id,
      pushLabel: (scenario.placeholders && scenario.placeholders.supervision_label_id)
        || DEFAULT_PLACEHOLDERS.supervision_label_id,
      pushEvent: (scenario.placeholders && scenario.placeholders.event_label_id)
        || DEFAULT_PLACEHOLDERS.event_label_id,
    }
    for (const action of scenario.actions || []) {
      const cmdId = idMap[action.type]
      const span = document.querySelector('.cmdValue[data-cmd_id="' + cmdId + '"]')
      if (!span) throw new Error('no cmdValue span bound to cmd_id ' + cmdId + ' for ' + action.type)
      span.innerHTML = String(action.value)
      await flush()
    }
    await flush()

    const root = document.querySelector('.siaDC09')
    const badge = root.querySelector('.siaDC09-badge')
    const label = root.querySelector('.siaDC09-label')
    const event = root.querySelector('.siaDC09-event')
    result.badgeClass = badge ? badge.getAttribute('class') : null
    result.labelText = label ? label.textContent.trim() : null
    result.eventText = event ? event.textContent.trim() : null
    result.title = badge ? badge.getAttribute('title') : null
    result.ok = true
  } catch (e) {
    result.error = e.message
  }
  return result
}

async function main() {
  const scenarios = JSON.parse(process.argv[2] || '[]')
  const results = []
  for (const scenario of scenarios) {
    results.push(await runScenario(scenario))
  }
  process.stdout.write(JSON.stringify(results) + '\n')
}

main()
