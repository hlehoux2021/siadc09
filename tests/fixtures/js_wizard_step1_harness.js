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
  <input type="checkbox" class="eqLogicAttr siaDC09-media-field" data-l2key="media_enabled">
  <div id="siaDC09-media-nomedia" style="display:none"></div>
  <div id="siaDC09-media-body" style="display:none">
    <div id="siaDC09-media-profile-group"><p id="siaDC09-media-lock-note" style="display:none"><span></span></p></div>
    <input type="hidden" class="eqLogicAttr siaDC09-media-field" data-l2key="media_transport">
    <input type="radio" name="siaDC09-media-transport" class="siaDC09-transport-radio siaDC09-transport-field siaDC09-profile-field" value="url">
    <input type="radio" name="siaDC09-media-transport" class="siaDC09-transport-radio siaDC09-transport-field siaDC09-profile-field" value="ftps">
    <div id="siaDC09-media-url-group" style="display:none"><input class="eqLogicAttr" data-l2key="frigate_media_url_template"></div>
    <p id="siaDC09-media-ftps-note" style="display:none"></p>
  </div>
  <div id="siaDC09-zone-content"></div>
  <a id="bt_siaDC09_toggleAdvanced"><i id="siaDC09-advbar-icon" class="fas fa-chevron-right"></i><span id="siaDC09-advbar-title-text"></span><span id="siaDC09-advbar-hint"></span></a>
  <div id="siaDC09-aes-row" style="display:none"></div>
  <div id="siaDC09-advanced" style="display:none">
  <div class="siaDC09-field">
  <select class="eqLogicAttr siaDC09-profile-field" data-l2key="supervision_format">
    <option value="sia-dcs">sia-dcs</option><option value="null">null</option>
    <option value="none">none</option>
  </select>
  </div>
  <div class="siaDC09-field">
  <input type="number" class="eqLogicAttr siaDC09-profile-field" data-l2key="supervision_interval">
  </div>
  <div class="siaDC09-field">
  <input type="checkbox" class="eqLogicAttr siaDC09-profile-field" data-l2key="rp_enabled">
  </div>
  <div class="siaDC09-field">
  <input type="number" class="eqLogicAttr siaDC09-profile-field" data-l2key="rp_interval">
  </div>
  <input type="checkbox" class="eqLogicAttr siaDC09-media-field siaDC09-profile-field" data-l2key="media_snapshot_enabled">
  <select class="eqLogicAttr siaDC09-media-field siaDC09-profile-field" data-l2key="media_snapshot_format"><option value="U">U</option><option value="V">V</option></select>
  <input type="checkbox" class="eqLogicAttr siaDC09-media-field siaDC09-profile-field" data-l2key="media_clip_enabled">
  <select class="eqLogicAttr siaDC09-media-field siaDC09-profile-field" data-l2key="media_clip_format"><option value="U">U</option><option value="V">V</option></select>
  <input type="checkbox" class="eqLogicAttr siaDC09-media-field siaDC09-profile-field" data-l2key="media_single_tag">
  <div id="siaDC09-media-single-tag-help" style="display:none"></div>
  <div id="siaDC09-ext-choice">
    <input type="radio" name="siaDC09-ext-mode" class="siaDC09-ext-radio siaDC09-media-field siaDC09-profile-field" value="1">
    <code id="siaDC09-ext-example-single"></code>
    <input type="radio" name="siaDC09-ext-mode" class="siaDC09-ext-radio siaDC09-media-field siaDC09-profile-field" value="0">
    <code id="siaDC09-ext-example-multi"></code>
  </div>
  <div id="siaDC09-ftps-card" style="display:none">
    <div class="siaDC09-field"><input class="eqLogicAttr" data-l2key="ftps_host"></div>
    <div class="siaDC09-field"><input type="number" class="eqLogicAttr" data-l2key="ftps_port"></div>
    <div class="siaDC09-field"><input class="eqLogicAttr" data-l2key="ftps_user"></div>
    <div class="siaDC09-field"><input type="password" class="eqLogicAttr" data-l2key="ftps_password"></div>
    <div class="siaDC09-field"><input class="eqLogicAttr" data-l2key="ftps_folder"></div>
    <input type="radio" name="siaDC09-ftps-cert" class="siaDC09-ftps-cert-radio" value="public">
    <input type="radio" name="siaDC09-ftps-cert" class="siaDC09-ftps-cert-radio" value="selfsigned">
    <div id="siaDC09-ftps-fingerprint-group" class="siaDC09-field" style="display:none"><input class="eqLogicAttr" data-l2key="ftps_cert_fingerprint"></div>
  </div>
  <p id="siaDC09-lock-caption" style="display:none"><span></span><a id="bt_siaDC09_goCustom"></a></p>
  </div>
  <div id="siaDC09-step2-errors" style="display:none"></div>
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
const peEnd = source.indexOf('// ===== WIZARD NAVIGATION =====')
if (peStart === -1 || peEnd === -1 || peEnd < peStart) {
  throw new Error('printEqLogic not found in desktop/js/siaDC09.js')
}
window.siaDC09_initDiagnosticTab = () => {}
window.siaDC09_showStep = () => {}
window.siaDC09_currentStep = () => 0 // config mode: saveEqLogic keeps the zone mappings alone
window.siaDC09_populateConfigSummary = () => {}
window.eval(source.match(/var SIADC09_WIZARD_DONE = \d+/)[0])
window.eval(source.slice(peStart, peEnd))

// Step 2 summary helpers live below the slice; load the pure ones.
const sumStart = source.indexOf('function siaDC09_isOn')
const sumFn = source.indexOf('function siaDC09_mediaSummaryLine')
window.eval(source.slice(sumStart, source.indexOf('\n}\n', sumFn) + 3))

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
const mediaErrors = []
const mediaErrorLists = []
const ftpsErrorLists = []
const finishErrors = []
const saved = []
for (const action of scenario.actions || []) {
  if (action.op === 'apply') window.siaDC09_applyProfile(action.profile, action.fill)
  else if (action.op === 'validateAdvanced') validate.push(window.siaDC09_validateAdvanced())
  else if (action.op === 'click') $(action.selector)[0].click()
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
  else if (action.op === 'mediaError') mediaErrors.push(window.siaDC09_mediaConfigError())
  else if (action.op === 'mediaErrors') mediaErrorLists.push(window.siaDC09_mediaConfigErrors())
  else if (action.op === 'mediaSummary') summaries.push(window.siaDC09_mediaSummaryLine(action.cfg))
  else if (action.op === 'ftpsErrors') ftpsErrorLists.push(window.siaDC09_ftpsConfigErrors())
  else if (action.op === 'finishError') finishErrors.push(window.siaDC09_finishConfigError())
  else if (action.op === 'openIfIncomplete') window.siaDC09_openAdvancedIfFtpsIncomplete()
  else if (action.op === 'save') saved.push(window.saveEqLogic({ configuration: Object.assign({}, action.configuration || {}) }))
}

const out = { fields: {}, validate, summaries, mediaErrors, mediaErrorLists, ftpsErrorLists, finishErrors, saved }
for (const key of ['supervision_format', 'supervision_interval', 'rp_interval']) out.fields[key] = field(key).val()
out.fields.rp_enabled = field('rp_enabled').is(':checked')
out.media = {}
for (const key of ['media_snapshot_format', 'media_clip_format']) out.media[key] = field(key).val()
for (const key of ['media_enabled', 'media_snapshot_enabled', 'media_clip_enabled', 'media_single_tag']) {
  out.media[key] = field(key).is(':checked')
}
out.locked = $('.siaDC09-locked').length
out.greyed = $('.siaDC09-field-locked').length
out.opacityDimmed = $('.siaDC09-profile-field').filter(function() { return this.style.opacity === '0.6' }).length
out.readonlyInputs = $('input[readonly]').length
out.selectedProfile = $('#siaDC09-csr-profile').val()
out.advancedVisible = $('#siaDC09-advanced').css('display') !== 'none'
const shown = sel => $(sel).css('display') !== 'none'
out.step1Media = {
  radiosLocked: $('.siaDC09-transport-radio.siaDC09-locked').length,
  radiosAria: $('.siaDC09-transport-radio[aria-disabled="true"]').length,
  bodyVisible: shown('#siaDC09-media-body'), ftpsNoteVisible: shown('#siaDC09-media-ftps-note'),
  ftpsCardVisible: shown('#siaDC09-ftps-card'), formatsVisible: shown('#siaDC09-zone-content'),
  transport: field('media_transport').val(),
  radioChecked: $('.siaDC09-transport-radio:checked').val() || null,
  groupGrey: $('#siaDC09-media-profile-group').hasClass('siaDC09-subzone-locked'),
  lockNote: shown('#siaDC09-media-lock-note') ? $('#siaDC09-media-lock-note > span').text() : null
}
out.ftps = {
  fingerprintVisible: shown('#siaDC09-ftps-fingerprint-group'),
  certChecked: $('.siaDC09-ftps-cert-radio:checked').val() || null,
  port: field('ftps_port').val(), fingerprint: field('ftps_cert_fingerprint').val(),
  lockedOrReadonly: $('#siaDC09-ftps-card .siaDC09-locked, #siaDC09-ftps-card [readonly], #siaDC09-ftps-card .siaDC09-profile-field, #siaDC09-ftps-card .siaDC09-field-locked, #siaDC09-ftps-card [aria-disabled]').length,
  invalid: $('#siaDC09-ftps-card .siaDC09-field-invalid').map(function() { return $(this).attr('data-l2key') }).get(),
  values: { host: field('ftps_host').val(), user: field('ftps_user').val(), password: field('ftps_password').val(), folder: field('ftps_folder').val() }
}
out.mediaUrlVisible =$('#siaDC09-media-url-group').css('display') !== 'none'
const $box = field('media_enabled')
out.mediaBox = { greyed: $box.css('pointer-events') === 'none', ariaDisabled: $box.attr('aria-disabled') === 'true' }
out.nomediaVisible = $('#siaDC09-media-nomedia').css('display') !== 'none'
out.singleTagDisabled = field('media_single_tag').prop('disabled')
out.singleTagChecked = field('media_single_tag').is(':checked')
const $radios = $('.siaDC09-ext-radio')
out.extChoice = {
  visible: $('#siaDC09-ext-choice').css('display') !== 'none',
  disabled: $radios.filter('[value="1"]').prop('disabled'),
  single: $radios.filter('[value="1"]').is(':checked'),
  multi: $radios.filter('[value="0"]').is(':checked'),
  reasonVisible: $('#siaDC09-media-single-tag-help').css('display') !== 'none',
  exampleSingle: $('#siaDC09-ext-example-single').text(),
  exampleMulti: $('#siaDC09-ext-example-multi').text()
}
out.caption = $('#siaDC09-lock-caption').css('display') !== 'none' ? $('#siaDC09-lock-caption > span').text() : null
out.advancedBar = { expanded: $('#bt_siaDC09_toggleAdvanced').attr('aria-expanded') || null, title: $('#siaDC09-advbar-title-text').text() }
out.step2Errors = $('#siaDC09-step2-errors').html()
// Every locked field must be readonly or aria-disabled.
out.lockedUnexposed = $('.siaDC09-locked').filter(function() {
  return !this.readOnly && this.getAttribute('aria-disabled') !== 'true'
}).length
out.frigateValue = field('frigate_media_url_template').val()
out.frigateInvalid = field('frigate_media_url_template').hasClass('siaDC09-field-invalid')
out.errors = $('#siaDC09-step1-errors').html()
process.stdout.write(JSON.stringify(out) + '\n')
