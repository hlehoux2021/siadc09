/**
 * DOM flow harness for the wizard buttons of siaDC09.js (story 17.9).
 *
 * Loads the WHOLE desktop/js/siaDC09.js into a jsdom window with jQuery, the wizard markup
 * and stubs for the Jeedom core calls. Every stub answers synchronously from the scenario
 * and records its call, so a test reads the exact call order.
 *
 * Usage: node js_wizard_flow_harness.js '<scenario_json>'
 *
 * Scenario: {
 *   "fields":  {l2key: value|bool},            initial step 1 values
 *   "daemon":  "ok" | "nok" | "error",          getDeamonInfo answer (error = AJAX error)
 *   "confirm": [bool, ...],                     jeeDialog.confirm answers, in order (default true)
 *   "save":    ["ok"|"error", ...],             jeedom.eqLogic.save outcomes, in order (default ok)
 *   "stop":    "ok" | "error",                  jeedom.plugin.deamonStop outcome
 *   "test":    "pending"|"ok"|"nak"|"fail"|"error",  testConnection answer (pending = never)
 *   "actions": [ {"op": "showStep", "step": n} | {"op": "click", "selector": css} |
 *                {"op": "snapshot"} | {"op": "fields", "fields": {...}} ]
 * }
 * Output: { "calls": [...], "snapshots": [ {step, buttons, banner, ...} ] }
 */

'use strict'

const { JSDOM } = require('./../../node_modules/jsdom')
const fs = require('fs')
const path = require('path')

const PROJECT_ROOT = path.resolve(__dirname, '../..')
const scenario = JSON.parse(process.argv[2] || '{}')

const group = (inner) => `<div class="siaDC09-field"><label></label>${inner}</div>`

const dom = new JSDOM(`<!DOCTYPE html><html><body>
  <div id="div_alert"></div>
  <div class="eqLogic">
    <input type="hidden" class="eqLogicAttr" data-l2key="sia_wizard_step">
    <a class="btn btn-warning btn-sm" id="bt_restartWizard">Relancer</a>
    <div id="siaDC09-config-summary" style="display:none;"></div>
    <div id="siaDC09-wizard">
      <ul id="siaDC09-stepper"><li data-step="1">1</li><li data-step="2">2</li><li data-step="3">3</li></ul>
      <div id="siaDC09-step1" class="siaDC09-step" style="display:none;">
        ${group('<select id="siaDC09-csr-profile" class="eqLogicAttr" data-l2key="csr_profile"><option value=""></option></select>')}
        ${group('<input class="eqLogicAttr" data-l2key="csr_ip">')}
        ${group('<input class="eqLogicAttr" data-l2key="csr_port">')}
        ${group('<select class="eqLogicAttr" data-l2key="transport"><option value="udp">udp</option></select>')}
        ${group('<input class="eqLogicAttr" data-l2key="account_number">')}
        ${group('<input type="checkbox" class="eqLogicAttr" data-l2key="encryption_enabled">')}
        ${group('<input class="eqLogicAttr" data-l2key="encryption_key">')}
        ${group('<input type="checkbox" class="eqLogicAttr siaDC09-media-field" id="siaDC09-media-enabled" data-l2key="media_enabled">')}
        <div id="siaDC09-media-url-group" style="display:none;">${group('<input class="eqLogicAttr" data-l2key="frigate_media_url_template">')}</div>
        <div id="siaDC09-step1-errors" class="alert alert-danger" role="alert" style="display:none;"></div>
        <a class="btn btn-success" id="bt_step1Next">Suivant</a>
      </div>
      <div id="siaDC09-step2" class="siaDC09-step" style="display:none;">
        <div id="siaDC09-step2-summary"></div>
        <div id="siaDC09-step2-spinner" style="display:none;"></div>
        <div id="siaDC09-step2-result" style="display:none;"></div>
        <a id="bt_siaDC09_toggleAdvanced" aria-expanded="false"><i id="siaDC09-advbar-icon"></i><span id="siaDC09-advbar-title-text"></span><span id="siaDC09-advbar-hint"></span></a>
        <div id="siaDC09-advanced" style="display:none;">
          <p id="siaDC09-lock-caption" style="display:none;"><span></span><a id="bt_siaDC09_goCustom">Personnalisé</a></p>
          ${group('<select class="eqLogicAttr siaDC09-profile-field" data-l2key="supervision_format"><option value="none">none</option><option value="sia-dcs">sia-dcs</option><option value="null">null</option></select>')}
          ${group('<input type="number" class="eqLogicAttr siaDC09-profile-field" data-l2key="supervision_interval">')}
          ${group('<input type="checkbox" class="eqLogicAttr siaDC09-profile-field" data-l2key="rp_enabled">')}
          ${group('<input type="number" class="eqLogicAttr siaDC09-profile-field" data-l2key="rp_interval">')}
        </div>
        <div id="siaDC09-step2-errors" style="display:none;"></div>
        <a class="btn btn-default" id="bt_step2Back">Modifier</a>
        <a class="btn btn-default" id="bt_step2Retest">Relancer le test</a>
        <a class="btn btn-warning" id="bt_step2Skip">Ignorer</a>
        <a class="btn btn-success disabled" id="bt_step2Next" disabled aria-disabled="true" tabindex="-1">Suivant</a>
      </div>
      <div id="siaDC09-step3" class="siaDC09-step" style="display:none;">
        <div id="siaDC09-step3-warning" style="display:none;"></div>
        <div id="siaDC09-step3-errors" style="display:none;"></div>
        <table><tbody id="siaDC09-zone-tbody"></tbody></table>
        <select id="siaDC09_notifyKind" class="eqLogicAttr" data-l2key="sia_notify_kind"><option value="cmd">cmd</option><option value="internal">internal</option></select>
        <input type="hidden" class="eqLogicAttr" data-l2key="sia_notify_cmd_id">
        <div id="siaDC09-notify-error" style="display:none;"></div>
        <a class="btn btn-success" id="bt_step3Finish">Terminer</a>
      </div>
    </div>
  </div>
  <table id="table_cmd"><tbody></tbody></table>
</body></html>`, { runScripts: 'dangerously' })

const window = dom.window
window.eval(fs.readFileSync(path.join(PROJECT_ROOT, 'node_modules/jquery/dist/jquery.js'), 'utf8'))
const $ = window.$

const calls = []
const record = (name) => calls.push(name)
const queues = { confirm: (scenario.confirm || []).slice(), save: (scenario.save || []).slice() }
const next = (name, fallback) => (queues[name].length ? queues[name].shift() : fallback)

// ---- Jeedom core stubs ----
$.fn.sortable = function() { return this }
$.fn.showAlert = function(opts) { record('alert:' + (opts && opts.message)); return this }
$.fn.getValues = function() {
  return [{ id: 1, configuration: { sia_wizard_step: $('.eqLogicAttr[data-l2key="sia_wizard_step"]').val() } }]
}
window.siaDC09_csrProfiles = scenario.profiles || {}
for (const id of Object.keys(window.siaDC09_csrProfiles)) $("#siaDC09-csr-profile").append($("<option>").val(id).text(id))
window.jeeFrontEnd = {}
window.jeeDialog = {
  confirm: function(message, callback) { record('confirm'); callback(next('confirm', true)) }
}
window.jeedom = {
  eqLogic: {
    save: function(params) {
      record('save:' + params.eqLogics[0].configuration.sia_wizard_step)
      if (next('save', 'ok') === 'ok') params.success({})
      else params.error({ message: 'save failed' })
    },
    byId: function() { record('byId') }
  },
  plugin: {
    // jeedom.private: success receives data.result, an error reply calls error.
    getDeamonInfo: function(params) {
      record('getDeamonInfo:' + params.id)
      const state = scenario.daemon || 'nok'
      if (state === 'error') params.error({ message: 'probe failed' })
      else params.success({ state: state, launchable: 'nok' })
    },
    deamonStop: function(params) {
      record('deamonStop:' + params.id)
      if (scenario.stop === 'error') params.error({ message: 'stop failed' })
      else params.success({})
    }
  },
  cmd: { getSelectModal: function() {} }
}
$.ajax = function(opts) {
  const action = opts && opts.data && opts.data.action
  record('ajax:' + action)
  if (action !== 'testConnection') return
  const test = scenario.test || 'pending'
  // Story 17.12: "pending" keeps the callbacks so an "answer" action can deliver them late.
  if (test === 'pending') { heldTests.push(opts); return }
  deliver(opts, test)
}
const heldTests = []
function deliver(opts, test) {
  if (test === 'error') opts.error({}, 'error', 'boom')
  else opts.success({ state: 'ok', result: Object.assign({ status: test, detail: test }, scenario.testExtra || {}) })
}

window.eval(fs.readFileSync(path.join(PROJECT_ROOT, 'desktop/js/siaDC09.js'), 'utf8'))

const field = (key) => $(`.eqLogicAttr[data-l2key="${key}"]`)
const setFields = (fields) => {
  for (const [key, value] of Object.entries(fields || {})) {
    if (typeof value === 'boolean') field(key).prop('checked', value)
    else field(key).val(value)
  }
}

const BUTTONS = ['bt_restartWizard', 'bt_step2Back', 'bt_step1Next', 'bt_step2Retest', 'bt_step2Skip', 'bt_step2Next', 'bt_step3Finish']

function snapshot() {
  const visible = $('.siaDC09-step').filter(function() { return this.style.display !== 'none' })
  const buttons = {}
  for (const id of BUTTONS) {
    const $b = $('#' + id)
    buttons[id] = {
      disabledClass: $b.hasClass('disabled'),
      ariaDisabled: $b.attr('aria-disabled') || null,
      tabindex: $b.attr('tabindex') || null,
      disabledAttr: $b.attr('disabled') !== undefined
    }
  }
  const fieldErrors = {}
  $('.siaDC09-field.has-error').each(function() {
    const $f = $(this).find('.eqLogicAttr').first()
    const describedBy = $f.attr('aria-describedby') || null
    fieldErrors[$f.attr('data-l2key')] = {
      describedBy: describedBy,
      message: describedBy ? $('#' + describedBy).text().trim() : null
    }
  })
  const $banner = $('#siaDC09-step1-errors')
  const active = window.document.activeElement
  return {
    step: visible.length === 1 ? parseInt(visible.attr('id').replace('siaDC09-step', ''), 10) : null,
    wizardStepField: field('sia_wizard_step').val(),
    buttons: buttons,
    bannerVisible: $banner.css('display') !== 'none',
    bannerTitle: $banner.find('strong').first().text(),
    bannerItems: $banner.find('li').map(function() { return $(this).text() }).get(),
    fieldErrors: fieldErrors,
    helpBlocks: $('.siaDC09-field-error').length,
    focused: active && active.getAttribute ? active.getAttribute('data-l2key') : null,
    advancedVisible: $('#siaDC09-advanced').css('display') !== 'none',
    step2ResultVisible: $('#siaDC09-step2-result').css('display') !== 'none',
    step2ResultText: $('#siaDC09-step2-result').text(),
    step2ChecksCount: $('#siaDC09-step2-result .siaDC09-step2-checks li').length,
    spinnerVisible: $('#siaDC09-step2-spinner').css('display') !== 'none',
    activeTab: $('#siaDC09-stepper li.active').attr('data-step') || null,
    step2ErrorsVisible: $('#siaDC09-step2-errors').css('display') !== 'none',
    captionVisible: $('#siaDC09-lock-caption').css('display') !== 'none',
    profileValue: $('#siaDC09-csr-profile').val(),
    fieldValues: { csr_ip: field('csr_ip').val(), account_number: field('account_number').val() }
  }
}

setFields(scenario.fields)
const snapshots = []
for (const action of scenario.actions || []) {
  if (action.op === 'showStep') window.siaDC09_showStep(action.step)
  else if (action.op === 'click') $(action.selector).trigger('click')
  else if (action.op === 'fields') setFields(action.fields)
  else if (action.op === 'snapshot') snapshots.push(snapshot())
  else if (action.op === 'answer') heldTests.forEach(function(o) { deliver(o, action.status || 'ok') })
  else if (action.op === 'mark') record('--' + action.label)
}

process.stdout.write(JSON.stringify({ calls: calls, snapshots: snapshots }) + '\n')
