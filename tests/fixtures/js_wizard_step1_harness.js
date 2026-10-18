/**
 * DOM test harness for the wizard step 1 code of siaDC09.js (profile choice + validation).
 *
 * Loads the block from "function siaDC09_lockProfileFields" up to the "STEP 1 → STEP 2 ADVANCE"
 * banner into a jsdom window with jQuery, builds the step 1 fields from the scenario, runs
 * the scenario's actions and prints one JSON object to stdout.
 *
 * Usage: node js_wizard_step1_harness.js '<scenario_json>'
 *
 * Scenario: { "profiles": {id: preset}, "fields": {l2key: value|bool}, "actions": [
 *             {"op": "apply", "profile": id, "fill": bool} | {"op": "validate"} |
 *             {"op": "printEqLogic", "eqLogic": {...}} |
 *             {"op": "trigger", "selector": css, "value"?: v, "checked"?: bool} ] }
 * Output:   { "fields": {...}, "locked": N, "advancedVisible": bool, "errors": "...",
 *             "validate": [bool, ...] }
 */

'use strict'

const { JSDOM } = require('./../../node_modules/jsdom')
const fs = require('fs')
const path = require('path')

const PROJECT_ROOT = path.resolve(__dirname, '../..')
const START_MARKER = 'function siaDC09_lockProfileFields'
const END_MARKER = '// ===== STEP 1 → STEP 2 ADVANCE ====='

const scenario = JSON.parse(process.argv[2] || '{}')

const dom = new JSDOM(`<!DOCTYPE html><html><body>
  <select id="siaDC09-csr-profile"><option value=""></option></select>
  <input class="eqLogicAttr" data-l2key="account_number">
  <input class="eqLogicAttr" data-l2key="csr_ip">
  <input class="eqLogicAttr" data-l2key="csr_port">
  <input type="checkbox" class="eqLogicAttr" data-l2key="encryption_enabled">
  <input class="eqLogicAttr" data-l2key="encryption_key">
  <select class="eqLogicAttr siaDC09-profile-field" data-l2key="supervision_format">
    <option value="sia-dcs">sia-dcs</option><option value="null">null</option>
    <option value="none">none</option>
  </select>
  <input type="number" class="eqLogicAttr siaDC09-profile-field" data-l2key="supervision_interval">
  <input type="checkbox" class="eqLogicAttr siaDC09-profile-field" data-l2key="rp_enabled">
  <input type="number" class="eqLogicAttr siaDC09-profile-field" data-l2key="rp_interval">
  <div id="siaDC09-null-warning" style="display:none"></div>
  <div id="siaDC09-advanced" style="display:none"></div>
  <div id="siaDC09-step1-errors" style="display:none"></div>
</body></html>`, { runScripts: 'dangerously' })

const window = dom.window
const document = window.document
window.eval(fs.readFileSync(path.join(PROJECT_ROOT, 'node_modules/jquery/dist/jquery.js'), 'utf8'))
const $ = window.$

const source = fs.readFileSync(path.join(PROJECT_ROOT, 'desktop/js/siaDC09.js'), 'utf8')
const start = source.indexOf(START_MARKER)
const end = source.indexOf(END_MARKER)
if (start === -1 || end === -1 || end < start) {
  throw new Error('step 1 markers not found in desktop/js/siaDC09.js')
}
window.siaDC09_csrProfiles = scenario.profiles || {}
window.eval(source.slice(start, end))

// printEqLogic lives above the slice; load it with stubs for the wizard plumbing it calls.
const peStart = source.indexOf('function printEqLogic')
const peEnd = source.indexOf('function saveEqLogic')
if (peStart === -1 || peEnd === -1 || peEnd < peStart) {
  throw new Error('printEqLogic not found in desktop/js/siaDC09.js')
}
window.siaDC09_initDiagnosticTab = () => {}
window.siaDC09_showStep = () => {}
window.siaDC09_populateConfigSummary = () => {}
window.eval(source.slice(peStart, peEnd))

for (const id of Object.keys(window.siaDC09_csrProfiles)) {
  $('#siaDC09-csr-profile').append($('<option>').val(id).text(id))
}

const field = key => $(`.eqLogicAttr[data-l2key="${key}"]`)
for (const [key, value] of Object.entries(scenario.fields || {})) {
  if (typeof value === 'boolean') field(key).prop('checked', value)
  else field(key).val(value)
}

const validate = []
const summaries = []
for (const action of scenario.actions || []) {
  if (action.op === 'apply') window.siaDC09_applyProfile(action.profile, action.fill)
  else if (action.op === 'summary') summaries.push(window.siaDC09_periodicSummaryLines(action.cfg))
  else if (action.op === 'printEqLogic') {
    // Jeedom fills the form from the saved configuration before calling printEqLogic.
    for (const [key, value] of Object.entries(action.eqLogic.configuration || {})) {
      const $f = field(key)
      if ($f.is(':checkbox')) $f.prop('checked', value === '1' || value === 1 || value === true)
      else $f.val(value)
    }
    window.printEqLogic(action.eqLogic)
  }
  else if (action.op === 'trigger') {
    const $el = $(action.selector)
    if (action.checked !== undefined) $el.prop('checked', action.checked)
    if (action.value !== undefined) $el.val(action.value)
    $el.trigger('change')
  } else if (action.op === 'validate') validate.push(window.siaDC09_validateStep1())
}

const out = { fields: {}, validate, summaries }
for (const key of ['supervision_format', 'supervision_interval', 'rp_interval']) out.fields[key] = field(key).val()
out.fields.rp_enabled = field('rp_enabled').is(':checked')
out.locked = $('.siaDC09-locked').length
out.dimmed = $('.siaDC09-profile-field').filter(function() { return this.style.opacity === '0.6' }).length
out.readonlyInputs = $('input[readonly]').length
out.selectedProfile = $('#siaDC09-csr-profile').val()
out.advancedVisible = $('#siaDC09-advanced').css('display') !== 'none'
out.nullWarningVisible = $('#siaDC09-null-warning').css('display') !== 'none'
out.errors = $('#siaDC09-step1-errors').html()
process.stdout.write(JSON.stringify(out) + '\n')
