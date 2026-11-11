/* This file is part of Jeedom.
 *
 * Jeedom is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

$("#table_cmd").sortable({
  axis: "y",
  cursor: "move",
  items: ".cmd",
  placeholder: "ui-state-highlight",
  tolerance: "intersect",
  forcePlaceholderSize: true
})

var _siaDC09_testNakConfirmed = false

// ===== JEEDOM PLUGIN HOOKS =====

function printEqLogic(_eqLogic) {
  // Empty / absent csr_profile = Personnalisé (legacy equipment keeps its current values, unlocked).
  var savedProfile = _eqLogic.configuration && _eqLogic.configuration.csr_profile || ''
  $('#siaDC09-csr-profile').val(savedProfile)
  // Absent keys fall back to the daemon-side defaults (sia-dcs, RP off, 60 s), not to the first <option>.
  var cfgSaved = _eqLogic.configuration || {}
  if (!cfgSaved.supervision_format) $('.eqLogicAttr[data-l2key="supervision_format"]').val('sia-dcs')
  if (!cfgSaved.rp_interval) $('.eqLogicAttr[data-l2key="rp_interval"]').val(60)
  siaDC09_applyProfile(savedProfile, false)
  // Story 17.7: absent media keys = pre-17.7 behaviour (snapshot + clip, V, V, one tag).
  var mediaDefaults = { media_enabled: 1, media_snapshot_enabled: 1, media_clip_enabled: 1, media_snapshot_format: 'V', media_clip_format: 'V', media_single_tag: 1, media_transport: 'url' }
  Object.keys(mediaDefaults).forEach(function(key) {
    if (cfgSaved[key] !== undefined && cfgSaved[key] !== '') return
    var $f = $('.eqLogicAttr[data-l2key="' + key + '"]')
    if ($f.is(':checkbox')) $f.prop('checked', !!mediaDefaults[key])
    else $f.val(mediaDefaults[key])
  })
  // Story 13.5: the stored Alarm equipment stays selected; unlinking only removes our entries.
  $('#siaDC09-alarm-select').val(cfgSaved.alarm_eqlogic_id ? String(cfgSaved.alarm_eqlogic_id) : '')
  $('#bt_unlinkAlarm').toggle(!!cfgSaved.alarm_eqlogic_id)
  siaDC09_syncFtpsCertRadios()
  siaDC09_updateMediaFields()
  siaDC09_updateAesRow()
  siaDC09_setAdvancedOpen(false)
  // Ajax-like profiles (no media keys): the box stays greyed and unchecked after the defaults above.
  if (savedProfile) siaDC09_applyProfile(savedProfile, false)
  var wizardStep = parseInt(_eqLogic.configuration && _eqLogic.configuration.sia_wizard_step || 0)
  siaDC09_initDiagnosticTab(wizardStep)
  if (wizardStep >= SIADC09_WIZARD_DONE) {
    $('#siaDC09-wizard').hide()
    $('#siaDC09-config-summary').show()
    siaDC09_populateConfigSummary(_eqLogic)
  } else {
    $('#siaDC09-wizard').show()
    $('#siaDC09-config-summary').hide()
    var step = Math.max(1, wizardStep)
    siaDC09_showStep(step)
  }
}

function saveEqLogic(_eqLogic) {
  // « Certificat reconnu » means no pinned fingerprint: empty it (story 18.11).
  if ($('.siaDC09-ftps-cert-radio[value="public"]').is(':checked')) {
    _eqLogic.configuration.ftps_cert_fingerprint = ''
  }
  var step = siaDC09_currentStep()
  if (step === 3) {
    var mappings = []
    $('#siaDC09-zone-tbody tr').each(function() {
      var zoneName = $(this).attr('data-zone-name')
      // The row keeps the number it was displayed with — never recomputed here, so a number
      // already declared to the CSR stays attached to the same zone.
      var zoneNumber = parseInt($(this).attr('data-zone-number'), 10)
      var $cameraSelect = $(this).find('.siaDC09-zone-frigate-camera')
      var frigateCameraEqlogicId = $cameraSelect.val() || null
      mappings.push({
        zone_number: zoneNumber || null,
        zone_name: zoneName,
        frigate_camera_eqlogic_id: frigateCameraEqlogicId ? parseInt(frigateCameraEqlogicId) : null,
        frigate_camera_label: frigateCameraEqlogicId ? $cameraSelect.find(':selected').text() : null
      })
    })
    _eqLogic.configuration.sia_zone_mappings = mappings
  } else if (step > 0 && step < 3) {
    delete _eqLogic.configuration.sia_zone_mappings
  }
  // step === 0 (config mode) or step === 4: preserve saved sia_zone_mappings
  return _eqLogic
}

// ===== WIZARD NAVIGATION =====

function siaDC09_currentStep() {
  var $visible = $('.siaDC09-step:visible')
  if ($visible.length === 0) return 0
  var id = $visible.attr('id') || ''
  var match = id.match(/step(\d+)/)
  return match ? parseInt(match[1]) : 0
}

// Wizard buttons are <a class="btn">: the disabled attribute alone neither greys nor blocks
// them. Bootstrap's .btn.disabled does both (pointer-events: none); aria-disabled and
// tabindex=-1 take the link out of assistive tech and the tab order. Click handlers guard
// on hasClass('disabled') for keyboard activation.
function siaDC09_setButtonEnabled($btn, enabled) {
  if (enabled) {
    $btn.removeAttr('disabled').removeClass('disabled').attr('aria-disabled', 'false').removeAttr('tabindex')
  } else {
    $btn.attr('disabled', 'disabled').addClass('disabled').attr('aria-disabled', 'true').attr('tabindex', '-1')
  }
}

// The wizard has three steps (story 17.14). `sia_wizard_step` holds the step shown (1..3);
// SIADC09_WIZARD_DONE is the "wizard complete" value that selects config mode (PHP twin:
// the `< 4` launch guard in siaDC09::deamon_info()).
var SIADC09_WIZARD_DONE = 4

function siaDC09_showStep(step) {
  $('.siaDC09-step').hide()
  $('#siaDC09-step' + step).show()
  // Read-only stepper: the active tab follows the step shown.
  $('#siaDC09-stepper li').removeClass('active').removeAttr('aria-current')
  $('#siaDC09-stepper li[data-step="' + step + '"]').addClass('active').attr('aria-current', 'step')

  // A view shown again resets its own buttons (bug B1: Suivant stayed disabled after
  // « Relancer l'assistant »). Step 2 buttons and zones are reset by siaDC09_resetStep2Tests().
  if (step === 1) {
    siaDC09_setButtonEnabled($('#bt_step1Next'), true)
  }
  if (step === 2) {
    siaDC09_populateStep2Summary()
    siaDC09_openAdvancedIfFtpsIncomplete()
    // Story 18.12: nothing runs on arrival; the user presses the single test button.
    $('#siaDC09-step2-errors').empty().hide()
    siaDC09_resetStep2Tests(true)
  }
  if (step === 3) {
    // Zones and critical alerts share this step (former steps 3 and 4).
    siaDC09_setButtonEnabled($('#bt_step3Finish'), true)
    siaDC09_initNotifyTarget()
    // sia_zone_mappings has no corresponding .eqLogicAttr input (it's a JS-managed config
    // blob, not a rendered form field), so getValues('.eqLogicAttr') can never return it —
    // it only ever reflects fields actually tagged in the DOM. Fetch the real persisted
    // eqLogic from the server instead, or the saved camera mapping never pre-selects on
    // wizard reload (bug found live 2026-09-26): the zone table then re-saves with every
    // frigate_camera_eqlogic_id wiped to null, silently destroying the working mapping.
    var eqLogicId = $('.eqLogic').getValues('.eqLogicAttr')[0].id
    jeedom.eqLogic.byId({
      id: eqLogicId,
      error: function(error) {
        $('#div_alert').showAlert({ message: error.message, level: 'danger' })
      },
      success: function(fullEqLogic) {
        siaDC09_loadZoneData(fullEqLogic)
      }
    })
  }
}

function siaDC09_setWizardStep(step) {
  $('.eqLogicAttr[data-l2key="sia_wizard_step"]').val(step)
}

// ===== STEP 1 PROFILE / ADVANCED OPTIONS =====

// Locking uses readonly on inputs and pointer-events on select/checkbox: disabled controls may be
// skipped by Jeedom's getValues() serialisation, readonly ones are always saved.
// The media content keys (story 17.10) are locked only by a profile that declares media
// (lockMedia); a profile without media keys leaves them untouched.
// The transport radios (story 18.4) are locked only by a profile that declares media_transport (lockTransport).
function siaDC09_lockProfileFields(locked, lockMedia, lockTransport) {
  $('.siaDC09-profile-field').each(function() {
    var $f = $(this)
    var lock = $f.hasClass('siaDC09-transport-field')
      ? locked && !!lockTransport
      : locked && (lockMedia || !$f.hasClass('siaDC09-media-field'))
    var isInput = $f.is('input[type="number"], input[type="text"]')
    if (isInput) {
      $f.prop('readonly', lock)
    } else {
      $f.css('pointer-events', lock ? 'none' : '').attr('tabindex', lock ? '-1' : null)
    }
    // Every locked field exposes its state (readonly for text/number inputs, aria-disabled for the rest).
    // The grey look comes from siaDC09.css (.siaDC09-locked / .siaDC09-field-locked), not from opacity.
    $f.attr('aria-disabled', lock ? 'true' : null)
    $f.toggleClass('siaDC09-locked', lock).closest('.siaDC09-field').toggleClass('siaDC09-field-locked', lock)
  })
}

// pointer-events:none stops a mouse click on the control itself, but a click on its <label> still
// toggles it, and the keyboard (space, arrows) still reaches a focused select. A locked control
// (aria-disabled) therefore refuses the click and the select keys; disabled would not be saved.
$(document).on('click', 'input[type="checkbox"][aria-disabled="true"], input[type="radio"][aria-disabled="true"]', function(event) {
  event.preventDefault()
})
$(document).on('mousedown keydown', 'select[aria-disabled="true"]', function(event) {
  if (event.type === 'mousedown' || event.key !== 'Tab') event.preventDefault()
})

// ONE lock caption for the whole advanced panel (never per section, never per field).
// Text: « Fixé par le profil « {nom} ». Choisissez « Personnalisé » pour le modifier. »
// An empty label hides it (Personnalisé: no caption, no locked look).
// Story 18.4: the same lock, said once on step 1 at the bottom of the grey group « Contenu et mode d'envoi ».
function siaDC09_setMediaLockCaption(profileLabel) {
  $('#siaDC09-media-lock-note').toggle(!!profileLabel)
    .find('> span').text('{{Fixé par le profil}} « ' + profileLabel + ' ». {{Choisissez « Personnalisé » pour le modifier.}}')
  $('#siaDC09-media-profile-group').toggleClass('siaDC09-subzone-locked', !!profileLabel)
}

function siaDC09_setLockCaption(profileLabel) {
  var text = '{{Fixé par le profil}} « ' + profileLabel + ' ». {{Choisissez « Personnalisé » pour le modifier.}}'
  $('#siaDC09-lock-caption').toggle(!!profileLabel).find('> span').text(text)
}

// « Passer en Personnalisé » (Test step): exactly the profile select changed to Personnalisé on step 1
// (same change handler). No preset is touched, values are kept, and the test is NOT rerun.
function siaDC09_switchToCustom() {
  $('#siaDC09-csr-profile').val('').trigger('change')
}

// AES key field only while the encryption box is checked.
function siaDC09_updateAesRow() {
  $('#siaDC09-aes-row').toggle($('.eqLogicAttr[data-l2key="encryption_enabled"]').is(':checked'))
}
$(document).on('change', '.eqLogicAttr[data-l2key="encryption_enabled"]', siaDC09_updateAesRow)

// Advanced panel open/closed: the bar reads « Options avancées (cliquer pour replier) » when open.
function siaDC09_setAdvancedOpen(open) {
  $('#siaDC09-advanced').toggle(open)
  $('#bt_siaDC09_toggleAdvanced').attr('aria-expanded', open ? 'true' : 'false')
  $('#siaDC09-advbar-icon').toggleClass('fa-chevron-down', open).toggleClass('fa-chevron-right', !open)
  $('#siaDC09-advbar-title-text').text(open
    ? '{{Options avancées (cliquer pour replier)}}'
    : '{{Options avancées : contenu envoyé, supervision de la liaison}}')
  $('#siaDC09-advbar-hint').toggle(!open)
}

// Alarm media keys a profile may carry (stories 17.8, 17.10). Checkboxes take 0/1, selects take U/V.
// The content keys are filled AND locked by the profile (ADR-22). `media_enabled` is the user's
// choice: a profile only gives its default, never locks it; the Frigate address is never a profile key.
var SIADC09_PROFILE_MEDIA_CHECKBOXES = ['media_snapshot_enabled', 'media_clip_enabled', 'media_single_tag']
var SIADC09_PROFILE_MEDIA_SELECTS = ['media_snapshot_format', 'media_clip_format']
// Story 18.4: the transport is a profile key too (url | ftps); anything else is ignored.
var SIADC09_MEDIA_TRANSPORTS = ['url', 'ftps']

function siaDC09_profileDeclaresTransport(preset) {
  return SIADC09_MEDIA_TRANSPORTS.indexOf(preset.media_transport) !== -1
}

// A profile declares media when it carries any media key (media_enabled included).
function siaDC09_profileDeclaresMedia(preset) {
  return SIADC09_PROFILE_MEDIA_CHECKBOXES.concat(SIADC09_PROFILE_MEDIA_SELECTS, ['media_enabled', 'media_transport'])
    .some(function(key) { return preset[key] !== undefined })
}

function siaDC09_applyProfileMedia(preset) {
  SIADC09_PROFILE_MEDIA_CHECKBOXES.forEach(function(key) {
    if (preset[key] !== undefined) {
      $('.eqLogicAttr[data-l2key="' + key + '"]').prop('checked', !!parseInt(preset[key], 10))
    }
  })
  SIADC09_PROFILE_MEDIA_SELECTS.forEach(function(key) {
    if (preset[key] !== undefined) {
      $('.eqLogicAttr[data-l2key="' + key + '"]').val(preset[key])
    }
  })
  if (siaDC09_profileDeclaresTransport(preset)) {
    $('.eqLogicAttr[data-l2key="media_transport"]').val(preset.media_transport)
  }
  if (preset.media_enabled !== undefined) {
    $('.eqLogicAttr[data-l2key="media_enabled"]').prop('checked', !!parseInt(preset.media_enabled, 10))
  } else if (siaDC09_profileDeclaresMedia(preset)) {
    $('.eqLogicAttr[data-l2key="media_enabled"]').prop('checked', true)
  }
  siaDC09_updateMediaFields()
}

// Checkbox availability: greyed and unchecked when the chosen profile declares no media (Ajax).
// pointer-events + aria-disabled, not `disabled`, so Jeedom's serialisation still saves the 0.
function siaDC09_setMediaCardAvailable(available) {
  var $box = $('.eqLogicAttr[data-l2key="media_enabled"]')
  if (!available) $box.prop('checked', false)
  $box.css({ 'pointer-events': available ? '' : 'none', opacity: available ? '' : 0.6 })
    .attr('tabindex', available ? null : '-1').attr('aria-disabled', available ? null : 'true')
  $('#siaDC09-media-nomedia').toggle(!available)
  siaDC09_updateMediaFields()
}

// fill=true copies the preset values into the fields (user picked a profile);
// fill=false only sets lock state (reload of an already-saved equipment).
function siaDC09_applyProfile(profileId, fill) {
  var profiles = (typeof siaDC09_csrProfiles === 'object' && siaDC09_csrProfiles) || {}
  var preset = profileId ? profiles[profileId] : null
  if (!preset) {
    siaDC09_lockProfileFields(false)
    siaDC09_setMediaCardAvailable(true)
    siaDC09_setLockCaption('')
    siaDC09_setMediaLockCaption('')
    return
  }
  if (fill) {
    if (preset.supervision_format !== undefined) {
      $('.eqLogicAttr[data-l2key="supervision_format"]').val(preset.supervision_format)
    }
    if (preset.supervision_interval !== undefined) {
      $('.eqLogicAttr[data-l2key="supervision_interval"]').val(preset.supervision_interval)
    }
    if (preset.rp_enabled !== undefined) {
      $('.eqLogicAttr[data-l2key="rp_enabled"]').prop('checked', !!parseInt(preset.rp_enabled, 10))
    }
    if (preset.rp_interval !== undefined) {
      $('.eqLogicAttr[data-l2key="rp_interval"]').val(preset.rp_interval)
    }
    siaDC09_applyProfileMedia(preset)
  }
  var declaresMedia = siaDC09_profileDeclaresMedia(preset)
  var declaresTransport = siaDC09_profileDeclaresTransport(preset)
  siaDC09_lockProfileFields(true, declaresMedia, declaresTransport)
  siaDC09_setMediaCardAvailable(declaresMedia)
  // A profile without media keys (Ajax) leaves the content fields editable; the single caption
  // still says why the supervision fields are locked.
  siaDC09_setLockCaption(preset.label || profileId)
  siaDC09_setMediaLockCaption(declaresMedia || declaresTransport ? (preset.label || profileId) : '')
}

// Choosing a profile (step 1) or Personnalisé (step 1 or the Test step) goes through here.
// The advanced panel lives on the Test step and never opens by itself on a profile change.
$('#siaDC09-csr-profile').on('change', function() {
  siaDC09_applyProfile($(this).val(), true)
})

$('#bt_siaDC09_goCustom').on('click', function() {
  siaDC09_switchToCustom()
})

// ===== ALARM MEDIA OPTIONS (story 17.7) =====

function siaDC09_mediaState() {
  return {
    enabled: $('.eqLogicAttr[data-l2key="media_enabled"]').is(':checked'),
    snapshotOn: $('.eqLogicAttr[data-l2key="media_snapshot_enabled"]').is(':checked'),
    clipOn: $('.eqLogicAttr[data-l2key="media_clip_enabled"]').is(':checked'),
    snapshotFormat: $('.eqLogicAttr[data-l2key="media_snapshot_format"]').val() || 'V',
    clipFormat: $('.eqLogicAttr[data-l2key="media_clip_format"]').val() || 'V',
    // Story 18.4: anything but 'ftps' (absent, '' or 'url') is the address way.
    transport: $('.eqLogicAttr[data-l2key="media_transport"]').val() === 'ftps' ? 'ftps' : 'url'
  }
}

// Abbreviated URLs used in the extension examples (story 17.11). The shapes follow
// SIAMessageBuilder._format_media_tags: a space between URLs inside one extension,
// one bracketed extension per link otherwise.
var SIADC09_EXAMPLE_SNAPSHOT_URL = 'https://monsite/..../snapshot.jpg'
var SIADC09_EXAMPLE_CLIP_URL = 'https://monsite/..../clip.mp4'

function siaDC09_mediaExamples(format) {
  return {
    single: '[' + format + SIADC09_EXAMPLE_SNAPSHOT_URL + ' ' + SIADC09_EXAMPLE_CLIP_URL + ']',
    multi: '[' + format + SIADC09_EXAMPLE_SNAPSHOT_URL + '][' + format + SIADC09_EXAMPLE_CLIP_URL + ']'
  }
}

// Frigate address only when the box is checked (its value is kept when hidden). The extension
// choice is always visible; it is available only when photo and video are both sent with the
// same format. Otherwise it is greyed, nothing is selected, and the reason is shown. The saved
// key media_single_tag is only reset for mixed formats (a single tag holds one format only).
function siaDC09_updateMediaFields() {
  var m = siaDC09_mediaState()
  var ftps = m.transport === 'ftps'
  // Story 18.4: everything below the box exists only while it is ticked; the Frigate address
  // only under « adresse »; under FTPS the step 1 note points to the step 2 « Serveur FTPS » card.
  $('#siaDC09-media-body').toggle(m.enabled)
  $('#siaDC09-media-url-group').toggle(m.enabled && !ftps)
  $('#siaDC09-media-ftps-note').toggle(m.enabled && ftps)
  $('#siaDC09-zone-content').toggle(m.enabled && !ftps)
  siaDC09_updateFtpsCard(m.enabled && ftps)
  $('.siaDC09-transport-radio').each(function() { $(this).prop('checked', $(this).val() === m.transport) })
  var available = m.snapshotOn && m.clipOn && m.snapshotFormat === m.clipFormat
  var mixed = m.snapshotOn && m.clipOn && !available
  var $single = $('.eqLogicAttr[data-l2key="media_single_tag"]')
  if (mixed) $single.prop('checked', false)
  $single.prop('disabled', mixed)
  var examples = siaDC09_mediaExamples(m.snapshotFormat)
  $('#siaDC09-ext-example-single').text(examples.single)
  $('#siaDC09-ext-example-multi').text(examples.multi)
  var $radios = $('.siaDC09-ext-radio')
  $radios.prop('disabled', !available)
  $radios.filter('[value="1"]').prop('checked', available && $single.is(':checked'))
  $radios.filter('[value="0"]').prop('checked', available && !$single.is(':checked'))
  $('#siaDC09-ext-choice').css('opacity', available ? '' : 0.6)
  $('#siaDC09-media-single-tag-help').toggle(!available)
}

// The radios drive the saved checkbox; a locked radio (profile) ignores the click.
$(document).on('change', '.siaDC09-ext-radio', function() {
  if ($(this).hasClass('siaDC09-locked')) {
    siaDC09_updateMediaFields() // a locked radio moved by keyboard snaps back to the saved value
    return
  }
  // trigger('change'): the radios are not eqLogicAttr, so Jeedom only sees the form as modified
  // through the bound checkbox's change event (it also re-runs siaDC09_updateMediaFields).
  $('.eqLogicAttr[data-l2key="media_single_tag"]').prop('checked', $(this).val() === '1').trigger('change')
})

// The transport radios drive the saved hidden field (Jeedom saves a radio as 0/1, not as its value).
$(document).on('change', '.siaDC09-transport-radio', function() {
  if ($(this).hasClass('siaDC09-locked')) {
    siaDC09_updateMediaFields() // a locked radio snaps back to the saved value
    return
  }
  $('.eqLogicAttr[data-l2key="media_transport"]').val($(this).val()).trigger('change')
})

// Story 18.4: the media errors as [{key, message}], [] when consistent. Photo or Vidéo is
// required; the Frigate address only under the « adresse » transport (never under FTPS).
function siaDC09_mediaConfigErrors() {
  var m = siaDC09_mediaState()
  var errors = []
  if (!m.enabled) return errors
  if (!m.snapshotOn && !m.clipOn) {
    errors.push({ key: 'media_snapshot_enabled', message: "{{Photo / vidéo : choisissez au moins l'une des deux.}}" })
  }
  var url = ($('.eqLogicAttr[data-l2key="frigate_media_url_template"]').val() || '').trim()
  if (m.transport !== 'ftps' && !url) {
    errors.push({ key: 'frigate_media_url_template', message: "{{Adresse du serveur Frigate : obligatoire quand la levée de doute est activée.}}" })
  }
  return errors
}

// Returns the first error message, or '' when the media settings are consistent.
function siaDC09_mediaConfigError() {
  var errors = siaDC09_mediaConfigErrors()
  return errors.length ? errors[0].message : ''
}

// ===== FTPS SETTINGS CARD (story 18.11) =====

// The « Serveur FTPS » card of the step 2 advanced panel exists only under FTPS with the media box
// ticked. The certificate radios add no config key: an empty fingerprint is « certificat reconnu »,
// a filled one « auto-signé ». The FTPS inputs are never profile fields, so never locked.
var _siaDC09_ftpsRadioDriven = false

function siaDC09_ftpsFieldValue(key) {
  return $('.eqLogicAttr[data-l2key="' + key + '"]').val() || ''
}

function siaDC09_ftpsCertIsSelfSigned() {
  return $('.siaDC09-ftps-cert-radio[value="selfsigned"]').is(':checked')
}

function siaDC09_updateFtpsCard(show) {
  $('#siaDC09-ftps-card').toggle(show)
  if (!show) return
  if ($('.siaDC09-ftps-cert-radio:checked').length === 0) {
    $('.siaDC09-ftps-cert-radio[value="public"]').prop('checked', true)
  }
  $('#siaDC09-ftps-fingerprint-group').toggle(siaDC09_ftpsCertIsSelfSigned())
  var $port = $('.eqLogicAttr[data-l2key="ftps_port"]')
  if (($port.val() || '').toString().trim() === '') $port.val(21)
}

// A saved fingerprint means « auto-signé » (loading an equipment, « Faire confiance » filling the field).
function siaDC09_syncFtpsCertRadios() {
  var selfSigned = siaDC09_ftpsFieldValue('ftps_cert_fingerprint').trim() !== ''
  $('.siaDC09-ftps-cert-radio[value="selfsigned"]').prop('checked', selfSigned)
  $('.siaDC09-ftps-cert-radio[value="public"]').prop('checked', !selfSigned)
  $('#siaDC09-ftps-fingerprint-group').toggle(selfSigned)
}

$(document).on('change', '.eqLogicAttr[data-l2key="ftps_cert_fingerprint"]', function() {
  if (!_siaDC09_ftpsRadioDriven) siaDC09_syncFtpsCertRadios()
})

// The radios only drive what is shown; « reconnu » empties the fingerprint at save (saveEqLogic).
$(document).on('change', '.siaDC09-ftps-cert-radio', function() {
  $('#siaDC09-ftps-fingerprint-group').toggle(siaDC09_ftpsCertIsSelfSigned())
  // Radios are not eqLogicAttr: trigger the field so Jeedom sees the form as modified.
  _siaDC09_ftpsRadioDriven = true
  $('.eqLogicAttr[data-l2key="ftps_cert_fingerprint"]').trigger('change')
  _siaDC09_ftpsRadioDriven = false
})

// FTPS settings errors as [{key, message}], [] when complete or when FTPS is not the chosen way.
function siaDC09_ftpsConfigErrors() {
  var m = siaDC09_mediaState()
  var errors = []
  if (!m.enabled || m.transport !== 'ftps') return errors
  if (!siaDC09_ftpsFieldValue('ftps_host').trim()) {
    errors.push({ key: 'ftps_host', message: '{{Serveur FTPS : obligatoire.}}' })
  }
  var port = siaDC09_ftpsFieldValue('ftps_port').toString().trim()
  var portNumber = parseInt(port, 10)
  if (!/^[0-9]+$/.test(port) || portNumber < 1 || portNumber > 65535) {
    errors.push({ key: 'ftps_port', message: '{{Port : nombre entre 1 et 65535 requis}}' })
  }
  if (!siaDC09_ftpsFieldValue('ftps_user').trim()) {
    errors.push({ key: 'ftps_user', message: '{{Utilisateur FTPS : obligatoire.}}' })
  }
  if (!siaDC09_ftpsFieldValue('ftps_password')) {
    errors.push({ key: 'ftps_password', message: '{{Mot de passe FTPS : obligatoire.}}' })
  }
  // A fingerprint only counts under « auto-signé »; separators (: space -) are allowed.
  var fingerprint = siaDC09_ftpsFieldValue('ftps_cert_fingerprint').replace(/[\s:-]/g, '')
  if (siaDC09_ftpsCertIsSelfSigned() && fingerprint !== '' && !/^[0-9a-fA-F]{64}$/.test(fingerprint)) {
    errors.push({ key: 'ftps_cert_fingerprint', message: '{{Empreinte SHA-256 : 64 caractères hexadécimaux requis}}' })
  }
  return errors
}

// « Terminer » safety net: the first media error, else the FTPS messages (all of them, one line).
function siaDC09_finishConfigError() {
  var mediaError = siaDC09_mediaConfigError()
  if (mediaError) return mediaError
  return siaDC09_ftpsConfigErrors().map(function(err) { return err.message }).join(' ')
}

// Step 2 arrival: the advanced panel opens by itself while the FTPS settings are incomplete.
function siaDC09_openAdvancedIfFtpsIncomplete() {
  if (siaDC09_ftpsConfigErrors().length > 0) siaDC09_setAdvancedOpen(true)
}

$(document).on('change', '.siaDC09-media-field', siaDC09_updateMediaFields)

$('#bt_siaDC09_toggleAdvanced').on('click', function() {
  siaDC09_setAdvancedOpen(!$('#siaDC09-advanced').is(':visible'))
}).on('keydown', function(e) {
  // The bar is an <a role="button">: Enter and Space fold it, like a button.
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    $(this).trigger('click')
  }
})

// Summary lines [label, text] for the profile, the periodic frames and the reconnection policy.
// Absent keys read as the daemon-side defaults (sia-dcs, 60 s, RP off) — a legacy equipment.
function siaDC09_periodicSummaryLines(cfg) {
  var profiles = (typeof siaDC09_csrProfiles === 'object' && siaDC09_csrProfiles) || {}
  var profile = cfg.csr_profile ? profiles[cfg.csr_profile] : null
  var format = cfg.supervision_format || 'sia-dcs'
  var interval = parseInt(cfg.supervision_interval, 10) || 60
  var rpInterval = parseInt(cfg.rp_interval, 10) || 60
  // Checkbox config comes back as "0"/"1" strings — compare explicitly.
  var rpOn = cfg.rp_enabled === true || cfg.rp_enabled === '1' || cfg.rp_enabled === 1
  var supervision = format === 'none'
    ? 'aucune trame de supervision'
    : (format === 'null' ? 'NULL' : 'SIA-DCS') + ' toutes les ' + interval + ' s'
  return [
    ['Profil : ', profile ? (profile.label || cfg.csr_profile) : 'Personnalisé'],
    ['Supervision : ', supervision],
    ['Test cyclique (RP) : ', rpOn ? 'activé, toutes les ' + rpInterval + ' s' : 'désactivé'],
    ['Reconnexion : ', (cfg.retry_count || 6) + ' tentatives de reconnexion'],
  ]
}

// ===== STEP 1 VALIDATION =====

function siaDC09_validateStep1() {
  var errors = []
  var accountNumber = $('.eqLogicAttr[data-l2key="account_number"]').val().trim()
  var csrIp = $('.eqLogicAttr[data-l2key="csr_ip"]').val().trim()
  var csrPort = parseInt($('.eqLogicAttr[data-l2key="csr_port"]').val())
  var encEnabled = $('.eqLogicAttr[data-l2key="encryption_enabled"]').is(':checked')
  var encKey = $('.eqLogicAttr[data-l2key="encryption_key"]').val().trim()

  if (!accountNumber || !/^[0-9a-fA-F]{3,16}$/.test(accountNumber)) {
    errors.push({ key: 'account_number', message: '{{Numéro de compte : 3 à 16 caractères hexadécimaux requis}}' })
  }
  if (!csrIp || csrIp === 'TBD') {
    errors.push({ key: 'csr_ip', message: "{{Adresse IP de la centrale requise}}" })
  }
  if (isNaN(csrPort) || csrPort < 1 || csrPort > 65535) {
    errors.push({ key: 'csr_port', message: '{{Port : nombre entre 1 et 65535 requis}}' })
  }
  if (encEnabled && encKey) {
    if (!/^[0-9a-fA-F]+$/.test(encKey) || [32, 48, 64].indexOf(encKey.length) === -1) {
      errors.push({ key: 'encryption_key', message: '{{Clé AES : 32, 48 ou 64 caractères hexadécimaux requis}}' })
    }
  }
  if (encEnabled && !encKey) {
    errors.push({ key: 'encryption_key', message: "{{Clé AES requise quand le chiffrement est activé}}" })
  }

  siaDC09_mediaConfigErrors().forEach(function(err) { errors.push(err) })

  siaDC09_renderStep1Errors(errors)
  return errors.length === 0
}

// Advanced options (Test step, story 17.14), run before a test starts. A profile always gives
// valid values; only Personnalisé can be wrong. PHP twin: siaDC09::periodicFrameConfigError().
function siaDC09_validateAdvanced() {
  var errors = siaDC09_ftpsConfigErrors()
  var supFormat = $('.eqLogicAttr[data-l2key="supervision_format"]').val() || 'sia-dcs'
  var rpOn = $('.eqLogicAttr[data-l2key="rp_enabled"]').is(':checked')
  var rpInterval = parseInt($('.eqLogicAttr[data-l2key="rp_interval"]').val(), 10)
  var noPeriodicFrame = supFormat === 'none' && !rpOn
  var badRpInterval = rpOn && (isNaN(rpInterval) || rpInterval < 60 || rpInterval > 86400)
  if (noPeriodicFrame) {
    errors.push({ key: 'supervision_format', message: '{{Au moins une trame périodique est requise : activez la supervision ou le test cyclique (RP)}}' })
  }
  if (badRpInterval) {
    errors.push({ key: 'rp_interval', message: '{{Intervalle RP : nombre entre 60 et 86400 secondes requis}}' })
  }
  siaDC09_renderFieldErrors(errors, $('#siaDC09-step2-errors'), '{{Impossible de lancer le test :}}')
  return errors.length === 0
}

function siaDC09_renderStep1Errors(errors) {
  siaDC09_renderFieldErrors(errors, $('#siaDC09-step1-errors'))
}

// Banner listing every error + a message under each faulty field. An empty list clears both.
// The banner title defaults to « Impossible de continuer : »; step 2 passes its own.
function siaDC09_renderFieldErrors(errors, $banner, title) {
  $('.siaDC09-field-error').remove()
  $('.siaDC09-field-invalid').removeAttr('aria-describedby').removeAttr('aria-invalid')
    .removeClass('siaDC09-field-invalid').closest('.siaDC09-field').removeClass('has-error')

  if (errors.length === 0) {
    $banner.empty().hide()
    return
  }

  var $list = $('<ul style="margin:5px 0 0 0;">')
  var $first = null
  var openAdvanced = false
  errors.forEach(function(err) {
    $list.append($('<li>').text(err.message))
    var $field = $('.eqLogicAttr[data-l2key="' + err.key + '"]').first()
    if ($field.length === 0) return
    var msgId = 'siaDC09-error-' + err.key
    var $msg = $('<span class="help-block siaDC09-field-error">').attr('id', msgId)
      .append('<i class="fas fa-exclamation-circle"></i> ').append($('<span>').text(err.message))
    $field.after($msg)
    $field.addClass('siaDC09-field-invalid').attr('aria-describedby', msgId).attr('aria-invalid', 'true')
      .closest('.siaDC09-field').addClass('has-error')
    if ($field.closest('#siaDC09-advanced').length > 0) openAdvanced = true
    if (!$first) $first = $field
  })
  $banner.empty()
    .append($('<strong>').text(title || '{{Impossible de continuer :}}'))
    .append($list)
    .show()
  // Open the folded panel before focusing: a hidden field cannot take the focus.
  if (openAdvanced) siaDC09_setAdvancedOpen(true)
  if ($first) $first[0].focus()
}

// ===== DAEMON STOP BEFORE THE WIZARD (bug B3) =====

// Asks for confirmation when the daemon runs, then hands the caller a stop function.
// The caller must save sia_wizard_step (< 4: launchable='nok', the watchdog cannot restart
// the daemon) BEFORE calling stop(onStopped, onStopFailed). Not running, or a failed probe:
// no dialog and stop() continues at once. A cancelled dialog calls onCancel.
// jeedom.plugin.* calls go through jeedom.private: an error reply calls `error`, and
// `success` receives data.result directly.
function siaDC09_confirmStopDaemon(message, onProceed, onCancel) {
  var noStop = function(onStopped) { onStopped() }
  var stop = function(onStopped, onStopFailed) {
    jeedom.plugin.deamonStop({
      id: 'siaDC09',
      error: function(error) { onStopFailed(error) },
      success: function() { onStopped() }
    })
  }
  jeedom.plugin.getDeamonInfo({
    id: 'siaDC09',
    error: function() {
      onProceed(noStop)
    },
    success: function(info) {
      if (!info || info.state !== 'ok') {
        onProceed(noStop)
        return
      }
      jeeDialog.confirm(message, function(result) {
        if (result) {
          onProceed(stop)
        } else {
          onCancel()
        }
      })
    }
  })
}

// ===== STEP 1 → STEP 2 ADVANCE =====

$('#bt_step1Next').on('click', function() {
  var $btn = $(this)
  if ($btn.hasClass('disabled')) return
  if (!siaDC09_validateStep1()) return

  siaDC09_setButtonEnabled($btn, false)
  var reEnable = function() { siaDC09_setButtonEnabled($btn, true) }
  var showError = function(error) {
    reEnable()
    $('#div_alert').showAlert({ message: (error && error.message) || '{{Erreur}}', level: 'danger' })
  }

  // Running daemon: confirm, save step 2, stop it, then advance. The connection test needs it stopped.
  siaDC09_confirmStopDaemon('{{Le démon est en cours d\'exécution. Il sera arrêté pour le test. Continuer ?}}', function(stop) {
    siaDC09_setWizardStep(2)
    jeedom.eqLogic.save({
      type: 'siaDC09',
      eqLogics: [$('.eqLogic').getValues('.eqLogicAttr')[0]],
      error: showError,
      success: function() {
        stop(function() { siaDC09_showStep(2) }, showError)
      }
    })
  }, reEnable)
})

// ===== STEP 2: CONNECTION TEST =====

function siaDC09_populateStep2Summary() {
  var ip = $('.eqLogicAttr[data-l2key="csr_ip"]').val() || ''
  var port = $('.eqLogicAttr[data-l2key="csr_port"]').val() || ''
  var transport = ($('.eqLogicAttr[data-l2key="transport"]').val() || 'udp').toUpperCase()
  var account = $('.eqLogicAttr[data-l2key="account_number"]').val() || ''
  var $summary = $('#siaDC09-step2-summary').empty()
  $('<strong>').text('{{Centrale :}}').appendTo($summary)
  $summary.append(' ')
  $('<span>').text(ip + ':' + port + ' (' + transport + ')').appendTo($summary)
  $summary.append('<br>')
  $('<strong>').text('{{Compte :}}').appendTo($summary)
  $summary.append(' ')
  $('<span>').text(account).appendTo($summary)
  $summary.append('<br>')
  $('<strong>').text('{{Levée de doute :}}').appendTo($summary)
  $summary.append(' ')
  $('<span>').text(siaDC09_mediaSummaryLine(siaDC09_formMediaConfig())).appendTo($summary)
}

// Media settings as a plain config object, read from the form (step 2 summary).
function siaDC09_formMediaConfig() {
  var cfg = {}
  ;['media_enabled', 'media_snapshot_enabled', 'media_clip_enabled'].forEach(function(key) {
    cfg[key] = $('.eqLogicAttr[data-l2key="' + key + '"]').is(':checked') ? '1' : '0'
  })
  ;['media_transport', 'ftps_host', 'ftps_port', 'ftps_folder', 'frigate_media_url_template'].forEach(function(key) {
    cfg[key] = $('.eqLogicAttr[data-l2key="' + key + '"]').val() || ''
  })
  return cfg
}

function siaDC09_isOn(value) {
  return value === true || value === '1' || value === 1
}

// What is attached: « photo + vidéo », « photo » or « vidéo ».
function siaDC09_mediaWhat(cfg) {
  var parts = []
  if (cfg.media_snapshot_enabled === undefined || siaDC09_isOn(cfg.media_snapshot_enabled)) parts.push('photo')
  if (cfg.media_clip_enabled === undefined || siaDC09_isOn(cfg.media_clip_enabled)) parts.push('vidéo')
  return parts.join(' + ')
}

// Step 2 line 2 (EXPERIENCE.md « Summaries »). Never the password.
function siaDC09_mediaSummaryLine(cfg) {
  if (cfg.media_enabled !== undefined && cfg.media_enabled !== '' && !siaDC09_isOn(cfg.media_enabled)) {
    return 'désactivée'
  }
  var what = siaDC09_mediaWhat(cfg)
  if (what === '') return 'désactivée'
  if (cfg.media_transport === 'ftps') {
    if (!cfg.ftps_host) return what + ', sur un serveur FTPS (à renseigner)'
    return what + ', sur le serveur FTPS ' + cfg.ftps_host + ':' + (cfg.ftps_port || 21) +
      ' (' + (cfg.ftps_folder || 'dossier racine') + ')'
  }
  return what + ', par une adresse dans le message d\'alarme'
}

// Story 17.12: identifies the current test run. Leaving step 2 (or relaunching the test) bumps it,
// so the answer of an abandoned run is ignored when it finally arrives.
var _siaDC09_testRun = 0

// Failure view: the DUH sentence, the message that was sent, then the only two checks allowed
// (never the profile name, never advice to change a locked setting).
function siaDC09_renderStep2Failure(result) {
  var $box = $('<div class="alert alert-danger siaDC09-test-failure"><i class="fas fa-times-circle"></i> </div>')
  var sent = result.sent || null
  var isDuh = result.outcome === 'duh'
  if (isDuh) {
    $box.append($('<span>').text('{{La centrale de télésurveillance a reçu le message de test, mais l\'a refusé (DUH).}}'))
  } else {
    $box.append($('<span>').text(result.detail || ''))
  }
  if (sent) {
    var $sent = $('<p class="siaDC09-step2-sent"></p>')
    $('<strong>').text('{{Message envoyé :}}').appendTo($sent)
    $sent.append(' ')
    $('<span>').text(sent.type + ' — {{Compte :}} ' + sent.account + ' — ' + sent.transport).appendTo($sent)
    $box.append($sent)
  }
  if (isDuh) {
    $box.append($('<p></p>').text('{{Vérifiez :}}'))
    var $list = $('<ul class="siaDC09-step2-checks"></ul>')
    $('<li>').text('{{que le profil choisi correspond bien à votre centre de télésurveillance ;}}').appendTo($list)
    $('<li>').text('{{que le numéro de compte (#compte#) est celui que le centre a enregistré pour vous.}}'.replace('#compte#', sent ? sent.account : '')).appendTo($list)
    $box.append($list)
    $box.append($('<p></p>').text('{{Puis relancez le test.}}'))
  }
  return $box
}

// ===== STEP 2: TEST ORCHESTRATION (story 18.12) =====
//
// Nothing runs on arrival. The single button validates the advanced options, saves the form, then
// runs the SIA test and, under FTPS, the FTPS test. Result per test: _siaDC09_tests.sia is
// 'ok' | 'nak' | 'fail'; .ftps is the testFtps status (ok|untrusted|changed|error|unavailable).
// null means « not tested ». Only ok (and nak, behind its confirmation) count as passed.
var _siaDC09_tests = { sia: null, ftps: null }
var _siaDC09_hasTested = false
var _siaDC09_running = false
var SIADC09_AJAX_URL = 'plugins/siaDC09/core/ajax/siaDC09.ajax.php'

function siaDC09_ftpsTestActive() {
  var m = siaDC09_mediaState()
  return m.enabled && m.transport === 'ftps'
}

function siaDC09_allTestsPassed() {
  var s = _siaDC09_tests
  if (s.sia !== 'ok' && s.sia !== 'nak') return false
  return !siaDC09_ftpsTestActive() || s.ftps === 'ok'
}

function siaDC09_notTestedZones() {
  $('#siaDC09-step2-sia-body').empty().append($('<p class="siaDC09-help">').text('{{Pas encore testé.}}'))
  var ftps = siaDC09_ftpsTestActive()
  $('#siaDC09-step2-ftps').toggle(ftps)
  if (!ftps) {
    $('#siaDC09-step2-ftps-body').empty()
    return
  }
  var message = siaDC09_ftpsConfigErrors().length > 0
    ? '{{Réglages à compléter dans les options avancées ci-dessous.}}'
    : '{{Pas encore testé.}}'
  $('#siaDC09-step2-ftps-body').empty().append($('<p class="siaDC09-help">').text(message))
}

// The test button reads « Lancer » before the first test, « Relancer » after; the right-hand slot is
// Suivant only when every test passed, Ignorer otherwise (never both). Running: Ignorer is inert.
function siaDC09_refreshStep2Buttons() {
  var running = _siaDC09_running
  var $test = $('#bt_step2Retest')
  var label = running ? '{{Test en cours...}}' : (_siaDC09_hasTested ? '{{Relancer le test}}' : '{{Lancer le test}}')
  $('#bt_step2Retest-label').text(label)
  $test.toggleClass('btn-success', !_siaDC09_hasTested && !running).toggleClass('btn-default', _siaDC09_hasTested || running)
  siaDC09_setButtonEnabled($test, !running)
  // « Modifier la centrale » stays live in every state.
  siaDC09_setButtonEnabled($('#bt_step2Back'), true)
  var passed = !running && siaDC09_allTestsPassed()
  $('#bt_step2Next').toggle(passed)
  siaDC09_setButtonEnabled($('#bt_step2Next'), passed)
  $('#bt_step2Skip').toggle(!passed)
  siaDC09_setButtonEnabled($('#bt_step2Skip'), !running)
}

// Back to « Pas encore testé. ». `arrival` also forgets that a test ever ran (label « Lancer »).
function siaDC09_resetStep2Tests(arrival) {
  _siaDC09_tests = { sia: null, ftps: null }
  _siaDC09_testNakConfirmed = false
  _siaDC09_running = false
  if (arrival) _siaDC09_hasTested = false
  siaDC09_notTestedZones()
  siaDC09_refreshStep2Buttons()
}

// Editing a setting on step 2 invalidates the results (an answer still in flight is abandoned).
$(document).on('change input', '#siaDC09-advanced input, #siaDC09-advanced select', function() {
  if ($('#siaDC09-step2').css('display') === 'none') return
  _siaDC09_testRun++
  siaDC09_resetStep2Tests(false)
})

function siaDC09_runSiaTest(run, done) {
  var $body = $('#siaDC09-step2-sia-body')
  $body.empty().append($('<p><i class="fas fa-spinner fa-spin"></i> </p>').append($('<span>').text('{{Test en cours...}}')))
  $.ajax({
    type: 'POST',
    url: SIADC09_AJAX_URL,
    data: { action: 'testConnection', ajax: 1 },
    dataType: 'json',
    global: false,
    timeout: 35000,
    success: function(data) {
      if (run !== _siaDC09_testRun) return
      var result = data.result || {}
      var status = result.status || 'error'
      var $resultDiv
      if (status === 'ok') {
        _siaDC09_tests.sia = 'ok'
        $resultDiv = $('<div class="alert alert-success siaDC09-test-success"><i class="fas fa-check-circle"></i> </div>')
        $resultDiv.append($('<span>').text(result.detail || ''))
      } else if (status === 'nak') {
        _siaDC09_tests.sia = 'nak'
        $resultDiv = $('<div class="alert alert-warning siaDC09-test-warning"><i class="fas fa-exclamation-triangle"></i> </div>')
        $resultDiv.append($('<span>').text(result.detail || ''))
      } else {
        _siaDC09_tests.sia = 'fail'
        $resultDiv = siaDC09_renderStep2Failure(result)
      }
      $body.empty().append($resultDiv)
      done()
    },
    error: function() {
      if (run !== _siaDC09_testRun) return
      _siaDC09_tests.sia = 'fail'
      $body.empty().append('<div class="alert alert-danger siaDC09-test-failure"><i class="fas fa-times-circle"></i> {{Erreur de communication avec le serveur}}</div>')
      done()
    }
  })
}

// FTPS result views (EXPERIENCE.md « Wording »). The browser never holds a password result:
// the answer carries a status, a detail and, for a certificate refusal, the presented fingerprint.
function siaDC09_renderFtpsResult(result) {
  var status = result.status || 'error'
  var detail = result.detail || ''
  var $box
  if (status === 'ok') {
    $box = $('<div class="alert alert-success siaDC09-test-success"><i class="fas fa-check-circle"></i> </div>')
    $('<strong>').text('{{Serveur FTPS joignable}}').appendTo($box)
    var pinned = siaDC09_ftpsFieldValue('ftps_cert_fingerprint').trim() !== ''
    $box.append($('<p>').text(pinned
      ? "{{Certificat conforme à l'empreinte, identifiant accepté. Le dossier n'est vérifié qu'à la première alarme.}}"
      : "{{Certificat reconnu, identifiant accepté. Le dossier n'est vérifié qu'à la première alarme.}}"))
  } else if (status === 'untrusted' || status === 'changed') {
    $box = $('<div class="alert alert-danger siaDC09-test-failure"><i class="fas fa-times-circle"></i> </div>')
    $('<strong>').text(status === 'changed' ? '{{Le certificat a changé}}' : '{{Certificat non reconnu}}').appendTo($box)
    $box.append($('<p>').text(status === 'changed'
      ? "{{Le serveur ne présente pas l'empreinte enregistrée. Le mot de passe n'a PAS été envoyé. Si vous avez renouvelé le certificat, faites confiance à la nouvelle empreinte :}}"
      : "{{Le serveur présente un certificat qui n'est pas signé par une autorité publique. Comparez l'empreinte ci-dessous avec celle de votre serveur :}}"))
    var fingerprint = result.fingerprint || ''
    $('<code class="siaDC09-fingerprint-box">').text(fingerprint).appendTo($box)
    if (status === 'untrusted') $box.append($('<p>').text("{{Le mot de passe n'a pas été envoyé.}}"))
    $('<a class="btn btn-default siaDC09-ftps-trust">').attr('data-fingerprint', fingerprint)
      .text('{{Faire confiance à cette empreinte}}').appendTo($('<p>').appendTo($box))
  } else if (status === 'unavailable') {
    $box = $('<div class="alert alert-info"><i class="fas fa-info-circle"></i> </div>')
    $box.append($('<span>').text(detail))
  } else {
    $box = $('<div class="alert alert-danger siaDC09-test-failure"><i class="fas fa-times-circle"></i> </div>')
    var step = result.step ? " « " + result.step + " »" : ''
    $('<strong>').text("{{Échec à l'étape}}" + step).appendTo($box)
    $box.append($('<p>').text(detail))
  }
  return $box
}

function siaDC09_runFtpsTest(run, done) {
  var $body = $('#siaDC09-step2-ftps-body')
  $body.empty().append($('<p><i class="fas fa-spinner fa-spin"></i> </p>').append($('<span>').text('{{Test du serveur FTPS en cours...}}')))
  // No password in the request: the saved configuration is read server-side.
  $.ajax({
    type: 'POST',
    url: SIADC09_AJAX_URL,
    data: { action: 'testFtps', ajax: 1 },
    dataType: 'json',
    global: false,
    timeout: 35000,
    success: function(data) {
      if (run !== _siaDC09_testRun) return
      var result = data.result || {}
      _siaDC09_tests.ftps = result.status || 'error'
      $body.empty().append(siaDC09_renderFtpsResult(result))
      done()
    },
    error: function() {
      if (run !== _siaDC09_testRun) return
      _siaDC09_tests.ftps = 'error'
      $body.empty().append('<div class="alert alert-danger siaDC09-test-failure"><i class="fas fa-times-circle"></i> {{Erreur de communication avec le serveur}}</div>')
      done()
    }
  })
}

// SIA first, then FTPS under FTPS (both run even when the first fails: each zone tells its own story).
function siaDC09_runTests(run) {
  var finish = function() {
    _siaDC09_running = false
    siaDC09_refreshStep2Buttons()
  }
  siaDC09_runSiaTest(run, function() {
    if (!siaDC09_ftpsTestActive()) { finish(); return }
    siaDC09_runFtpsTest(run, finish)
  })
}

// « Faire confiance à cette empreinte »: fills the fingerprint (and so selects « auto-signé ») and
// starts nothing. The change clears the results, so the message is written after it.
$(document).on('click', '.siaDC09-ftps-trust', function() {
  var fingerprint = $(this).attr('data-fingerprint') || ''
  if (!fingerprint) return
  $('.eqLogicAttr[data-l2key="ftps_cert_fingerprint"]').val(fingerprint).trigger('change')
  siaDC09_syncFtpsCertRadios()
  $('#siaDC09-step2-ftps-body').empty().append($('<div class="alert alert-info">').text('{{Empreinte enregistrée. Relancez le test.}}'))
})

// « Modifier la centrale » — back to step 1, every value kept, nothing saved. Available while a
// test runs: the run is abandoned and its late answer ignored. showStep(1) revives step 1 buttons.
$('#bt_step2Back').on('click', function() {
  if ($(this).hasClass('disabled')) return
  _siaDC09_testRun++
  _siaDC09_running = false
  $('#siaDC09-step2-errors').empty().hide()
  siaDC09_showStep(1)
})

// The single test button. The tests read the SAVED configuration (core/ajax/siaDC09.ajax.php),
// so the advanced options are validated and the form saved first; invalid options run nothing.
$('#bt_step2Retest').on('click', function() {
  if ($(this).hasClass('disabled')) return
  if (!siaDC09_validateAdvanced()) return

  var run = ++_siaDC09_testRun
  _siaDC09_tests = { sia: null, ftps: null }
  _siaDC09_testNakConfirmed = false
  _siaDC09_hasTested = true
  _siaDC09_running = true
  siaDC09_refreshStep2Buttons()
  siaDC09_setWizardStep(2)
  jeedom.eqLogic.save({
    type: 'siaDC09',
    eqLogics: [$('.eqLogic').getValues('.eqLogicAttr')[0]],
    error: function(error) {
      if (run !== _siaDC09_testRun) return
      siaDC09_resetStep2Tests(false)
      $('#div_alert').showAlert({ message: (error && error.message) || '{{Erreur}}', level: 'danger' })
    },
    success: function() {
      if (run !== _siaDC09_testRun) return
      siaDC09_runTests(run)
    }
  })
})

// Step 3 warning: one line per test not passed (EXPERIENCE.md « Buttons of step 2 »).
function siaDC09_showStep3Warnings() {
  var tail = "{{le plugin ne pourra peut-être pas transmettre d'alarmes ni déposer la photo ou la vidéo.}}"
  var sia = _siaDC09_tests.sia
  var ftps = _siaDC09_tests.ftps
  var siaLabel = ''
  if (sia === null) siaLabel = '{{Connexion non testée}}'
  else if (sia === 'fail') siaLabel = '{{Test échoué}}'
  var ftpsLabel = ''
  if (siaDC09_ftpsTestActive() && ftps !== 'ok') {
    ftpsLabel = (ftps === null || ftps === 'unavailable') ? '{{Serveur FTPS non testé}}' : '{{Test du serveur FTPS échoué}}'
  }
  $('#siaDC09-step3-warning-sia').toggle(siaLabel !== '').find('span').text(siaLabel + ' : ' + tail)
  $('#siaDC09-step3-warning-ftps').toggle(ftpsLabel !== '').find('span').text(ftpsLabel + ' : ' + tail)
  $('#siaDC09-step3-warning').toggle(siaLabel !== '' || ftpsLabel !== '')
}

// Ignorer — advance to step 3 with one warning per test not passed
$('#bt_step2Skip').on('click', function() {
  if ($(this).hasClass('disabled')) return
  siaDC09_setWizardStep(3)
  jeedom.eqLogic.save({
    type: 'siaDC09',
    eqLogics: [$('.eqLogic').getValues('.eqLogicAttr')[0]],
    error: function(error) {
      $('#div_alert').showAlert({ message: error.message, level: 'danger' })
    },
    success: function() {
      siaDC09_showStep3Warnings()
      siaDC09_showStep(3)
    }
  })
})

// Suivant on Step 2 (visible only after a full success); a NAK keeps its confirmation dialog.
$('#bt_step2Next').on('click', function() {
  if ($(this).hasClass('disabled')) return
  if (_siaDC09_tests.sia === 'nak' && !_siaDC09_testNakConfirmed) {
    jeeDialog.confirm('{{La centrale a répondu NAK. Continuer malgré tout ?}}', function(ok) {
      if (ok) {
        _siaDC09_testNakConfirmed = true
        siaDC09_advanceToStep3()
      }
    })
  } else {
    siaDC09_advanceToStep3()
  }
})

function siaDC09_advanceToStep3() {
  siaDC09_setWizardStep(3)
  jeedom.eqLogic.save({
    type: 'siaDC09',
    eqLogics: [$('.eqLogic').getValues('.eqLogicAttr')[0]],
    error: function(error) {
      $('#div_alert').showAlert({ message: error.message, level: 'danger' })
    },
    success: function() {
      $('#siaDC09-step3-warning').hide()
      siaDC09_showStep(3)
    }
  })
}

// ===== RESTART WIZARD =====

$('#bt_restartWizard').on('click', function() {
  var $btn = $(this)
  if ($btn.hasClass('disabled')) return

  siaDC09_setButtonEnabled($btn, false)
  var reEnable = function() { siaDC09_setButtonEnabled($btn, true) }
  var showError = function(error) {
    reEnable()
    $('#div_alert').showAlert({ message: (error && error.message) || '{{Erreur}}', level: 'danger' })
  }

  // Step 0 is saved before the stop: launchable='nok', so the watchdog cannot restart the daemon.
  siaDC09_confirmStopDaemon('{{Le démon est en cours d\'exécution. Il sera arrêté. Continuer ?}}', function(stop) {
    siaDC09_setWizardStep(0)
    jeedom.eqLogic.save({
      type: 'siaDC09',
      eqLogics: [$('.eqLogic').getValues('.eqLogicAttr')[0]],
      error: showError,
      success: function() {
        stop(function() {
          reEnable()
          $('#siaDC09-config-summary').hide()
          $('#siaDC09-wizard').show()
          siaDC09_showStep(1)
        }, showError)
      }
    })
  }, reEnable)
})

// ===== STEP 3: ALARM LINK (story 13.5) =====

$('#siaDC09-alarm-select').on('change', function() {
  // Jeedom fills the form on page load and may fire « change » here before the equipment id is
  // set: byId() with no id answers « EqLogic inconnu ». Do nothing until the id is known.
  var eqLogicId = $('.eqLogic').getValues('.eqLogicAttr')[0].id
  if (!eqLogicId) return
  jeedom.eqLogic.byId({
    id: eqLogicId,
    error: function(error) { $('#div_alert').showAlert({ message: error.message, level: 'danger' }) },
    success: function(fullEqLogic) { siaDC09_loadZoneData(fullEqLogic) }
  })
})

function siaDC09_alarmAjax(action, alarmId, okMessage, done) {
  var $btn = $('#bt_linkAlarm, #bt_unlinkAlarm')
  $btn.addClass('disabled')
  $.ajax({
    type: 'POST',
    url: 'plugins/siaDC09/core/ajax/siaDC09.ajax.php',
    data: { action: action, alarm_id: alarmId, ajax: 1 },
    dataType: 'json',
    global: false,
    error: function() {
      $btn.removeClass('disabled')
      $('#div_alert').showAlert({ message: '{{Erreur}}', level: 'danger' })
    },
    success: function(data) {
      $btn.removeClass('disabled')
      if (data.state !== 'ok') {
        $('#div_alert').showAlert({ message: data.result || '{{Erreur}}', level: 'danger' })
        return
      }
      $('#div_alert').showAlert({ message: okMessage, level: 'success' })
      done()
    }
  })
}

$('#bt_linkAlarm').on('click', function() {
  var alarmId = $('#siaDC09-alarm-select').val()
  if (!alarmId) {
    $('#div_alert').showAlert({ message: '{{Choisissez un équipement Alarme}}', level: 'warning' })
    return
  }
  if ($(this).hasClass('disabled')) return
  // The zone/camera table is only persisted on « Terminer »: save it first so the link sees it.
  var eq = saveEqLogic($('.eqLogic').getValues('.eqLogicAttr')[0])
  jeedom.eqLogic.save({
    type: 'siaDC09',
    eqLogics: [eq],
    error: function(error) { $('#div_alert').showAlert({ message: (error && error.message) || '{{Erreur}}', level: 'danger' }) },
    success: function() {
      // The direct save does not clear Jeedom's dirty flag: reset it so no needless prompt appears.
      window.modifyWithoutSave = false
      jeeFrontEnd.modifyWithoutSave = false
      siaDC09_alarmAjax('linkAlarm', alarmId, '{{Commandes liées au plugin Alarme}}', function() {
        $('#bt_unlinkAlarm').show()
      })
    }
  })
})

$('#bt_unlinkAlarm').on('click', function() {
  if ($(this).hasClass('disabled')) return
  siaDC09_alarmAjax('unlinkAlarm', '', '{{Commandes retirées du plugin Alarme}}', function() {})
})

// ===== STEP 3: ZONE TABLE =====

function siaDC09_loadZoneData(eqLogic) {
  var savedMapping = (eqLogic && eqLogic.configuration && eqLogic.configuration.sia_zone_mappings) || []
  if (typeof savedMapping === 'string') {
    try { savedMapping = JSON.parse(savedMapping) } catch(e) { savedMapping = [] }
  }
  $.ajax({
    type: 'POST',
    url: 'plugins/siaDC09/core/ajax/siaDC09.ajax.php',
    data: { action: 'getFrigateCameras', ajax: 1 },
    dataType: 'json',
    global: false,
    success: function(data) {
      var cameras = (data.result || {}).cameras || []
      $('#siaDC09-step3-nocamera').toggle(cameras.length === 0)
      $.ajax({
        type: 'POST',
        url: 'plugins/siaDC09/core/ajax/siaDC09.ajax.php',
        data: { action: 'getZones', alarm_id: $('#siaDC09-alarm-select').val() || '', ajax: 1 },
        dataType: 'json',
        global: false,
        success: function(data2) {
          var result2 = data2.result || {}
          if (result2.error) {
            $('#siaDC09-step3-nozone').show()
            $('#siaDC09-zone-tbody').empty()
          } else {
            $('#siaDC09-step3-nozone').hide()
            siaDC09_loadZoneTable(result2.zones || [], savedMapping, cameras)
          }
        },
        error: function() {
          $('#siaDC09-step3-nozone').show()
        }
      })
    },
    error: function() {
      // Camera discovery failed — still load zones but with an empty camera dropdown
      $('#siaDC09-step3-nocamera').show()
      $.ajax({
        type: 'POST',
        url: 'plugins/siaDC09/core/ajax/siaDC09.ajax.php',
        data: { action: 'getZones', alarm_id: $('#siaDC09-alarm-select').val() || '', ajax: 1 },
        dataType: 'json',
        global: false,
        success: function(data2) {
          var result2 = data2.result || {}
          if (result2.error) {
            $('#siaDC09-step3-nozone').show()
          } else {
            $('#siaDC09-step3-nozone').hide()
            siaDC09_loadZoneTable(result2.zones || [], savedMapping, [])
          }
        },
        error: function() {
          $('#siaDC09-step3-nozone').show()
        }
      })
    }
  })
}

function siaDC09_loadZoneTable(zones, zoneMapping, cameras) {
  var $tbody = $('#siaDC09-zone-tbody')
  $tbody.empty()
  var mapping = zoneMapping || []
  // Highest number already assigned — a zone unknown to the saved mapping takes the next one,
  // so a number already declared to the CSR never shifts to another zone.
  var nextNumber = mapping.reduce(function(max, m) {
    return Math.max(max, parseInt(m.zone_number, 10) || 0)
  }, 0)
  zones.forEach(function(zoneName, index) {
    var saved = mapping.find(function(m) {
      return m.zone_name === zoneName
    }) || {}
    // Legacy mappings have no zone_number: fall back to table position.
    var zoneNumber = parseInt(saved.zone_number, 10) || 0
    if (!zoneNumber) {
      zoneNumber = mapping.length === 0 ? index + 1 : ++nextNumber
    }
    $tbody.append(siaDC09_buildZoneRow(zoneNumber, zoneName, saved, cameras))
  })
}

function siaDC09_buildZoneRow(zoneNumber, zoneName, saved, cameras) {
  var $tr = $('<tr>')
  $tr.append($('<td>').text(zoneNumber))
  $tr.append($('<td>').text(zoneName))

  // Single Frigate camera select — info_detect_person/info_url_snapshot are derived by
  // logicalId at alarm time (ADR-17), never stored as separate config fields.
  var $cameraSelect = $('<select class="form-control siaDC09-zone-frigate-camera">')
  $cameraSelect.append($('<option value="">').text('(aucune)'))
  ;(cameras || []).forEach(function(cam) {
    var $opt = $('<option>').val(cam.id).text(cam.label)
    if (saved.frigate_camera_eqlogic_id && String(saved.frigate_camera_eqlogic_id) === String(cam.id)) {
      $opt.prop('selected', true)
    }
    $cameraSelect.append($opt)
  })
  $tr.append($('<td>').append($cameraSelect))

  // The displayed <td> is for the user; these attributes are the serialization contract.
  $tr.attr('data-zone-number', zoneNumber)
  $tr.attr('data-zone-name', zoneName)
  return $tr
}

// ===== STEP 3: NOTIFICATION TARGET (former step 4, merged with the zones) =====

// An equipment command is picked through the modal; a Jeedom internal action (message,
// scenario) is not a cmd id, so it has its own selects. Empty kind means "cmd" — that is what
// installations configured before the internal option existed carry.
function siaDC09_initNotifyTarget() {
  var $kind = $('#siaDC09_notifyKind')
  if ($kind.val() !== 'internal') {
    $kind.val('cmd')
  }
  siaDC09_toggleNotifyTarget()
}

function siaDC09_toggleNotifyTarget() {
  var kind = $('#siaDC09_notifyKind').val()
  var internal = $('#siaDC09_notifyInternal').val()

  $('.siaDC09-notify-cmd').toggle(kind === 'cmd')
  $('.siaDC09-notify-internal').toggle(kind === 'internal')
  $('.siaDC09-notify-scenario').toggle(kind === 'internal' && internal === 'scenario')

  $('#siaDC09-notify-error, #siaDC09-notify-error-internal, #siaDC09-notify-error-scenario').hide()
}

// Shows the error that matches the missing field, so the message always names what to fix.
function siaDC09_validateNotifyTarget() {
  $('#siaDC09-notify-error, #siaDC09-notify-error-internal, #siaDC09-notify-error-scenario').hide()

  if ($('#siaDC09_notifyKind').val() !== 'internal') {
    if (!$('.eqLogicAttr[data-l2key="sia_notify_cmd_id"]').val()) {
      $('#siaDC09-notify-error').show()
      return false
    }
    return true
  }

  var internal = $('#siaDC09_notifyInternal').val()
  if (!internal) {
    $('#siaDC09-notify-error-internal').show()
    return false
  }
  if (internal === 'scenario' && !$('#siaDC09_notifyScenario').val()) {
    $('#siaDC09-notify-error-scenario').show()
    return false
  }
  return true
}

$('#siaDC09_notifyKind, #siaDC09_notifyInternal').on('change', siaDC09_toggleNotifyTarget)

$('#siaDC09_searchNotifyCmd').on('click', function() {
  jeedom.cmd.getSelectModal(
    { cmd: { type: 'action', subType: 'message' } },
    function(result) {
      $('.eqLogicAttr[data-l2key="sia_notify_cmd_human"]').val(result.human)
      $('.eqLogicAttr[data-l2key="sia_notify_cmd_id"]').val(result.cmd.id)
      $('#siaDC09-notify-error').hide()
    }
  )
})

// « Terminer »: the last step. Checks the Frigate address (safety net for an equipment saved outside
// the wizard) and the notification target, serialises the zone table, then writes the "wizard
// complete" step value and reloads into config mode.
$('#bt_step3Finish').on('click', function() {
  if ($(this).hasClass('disabled')) return

  var mediaError = siaDC09_finishConfigError()
  if (mediaError) {
    $('#siaDC09-step3-errors').text(mediaError).show()
    return
  }
  $('#siaDC09-step3-errors').hide()

  if (!siaDC09_validateNotifyTarget()) {
    return
  }

  var $btn = $(this)
  siaDC09_setButtonEnabled($btn, false)

  siaDC09_setWizardStep(SIADC09_WIZARD_DONE)
  jeedom.eqLogic.save({
    type: 'siaDC09',
    // saveEqLogic() serialises the zone table while step 3 is the visible step.
    eqLogics: [saveEqLogic($('.eqLogic').getValues('.eqLogicAttr')[0])],
    error: function(error) {
      siaDC09_setButtonEnabled($btn, true)
      $('#div_alert').showAlert({ message: error.message, level: 'danger' })
    },
    success: function() {
      // Reset Jeedom core's dirty-form flags before reloading — our own direct
      // jeedom.eqLogic.save() call above doesn't clear them, so without this the
      // reload triggers a spurious browser "leave page, unsaved changes?" prompt
      // (jeedom/core/desktop/common/js/utils.js:767-773), even though the save just
      // succeeded. Same reset Jeedom core itself performs after its own save button.
      window.modifyWithoutSave = false
      jeeFrontEnd.modifyWithoutSave = false
      // Reload the page — printEqLogic will detect sia_wizard_step=4 and show config mode
      window.location.reload()
    }
  })
})

// ===== CONFIG SUMMARY =====

function siaDC09_populateConfigSummary(eqLogic) {
  var cfg = (eqLogic && eqLogic.configuration) || {}

  // Connection summary
  var $conn = $('#siaDC09-summary-connection').empty()
  $('<div>').append(
    $('<strong>').text('Centrale : ')
  ).append(
    $('<span>').text((cfg.csr_ip || '') + ':' + (cfg.csr_port || '') + ' (' + ((cfg.transport || 'udp').toUpperCase()) + ')')
  ).appendTo($conn)
  siaDC09_periodicSummaryLines(cfg).forEach(function(line) {
    $('<div>').append($('<strong>').text(line[0])).append($('<span>').text(line[1])).appendTo($conn)
  })
  // Persisted checkbox config comes back as the string "0" when unchecked, not absent —
  // a bare truthy check on cfg.encryption_enabled treats "0" as truthy and always shows
  // "activé" (bug found live 2026-09-26). Compare explicitly.
  var encryptionOn = cfg.encryption_enabled === true || cfg.encryption_enabled === '1' || cfg.encryption_enabled === 1
  $('<div>').append(
    $('<strong>').text('Chiffrement : ')
  ).append(
    $('<span>').text(encryptionOn ? 'activé' : 'désactivé')
  ).appendTo($conn)

  // Levée de doute block (story 18.4), between Connexion and Zones. Never the password.
  var $media = $('#siaDC09-summary-media').empty()
  var mediaOff = cfg.media_enabled !== undefined && cfg.media_enabled !== '' && !siaDC09_isOn(cfg.media_enabled)
  if (mediaOff) {
    $('<em class="text-muted">').text('désactivée').appendTo($media)
  } else {
    var ftps = cfg.media_transport === 'ftps'
    var addLine = function(label, $value) {
      $('<div>').append($('<strong>').text(label)).append($value).appendTo($media)
    }
    addLine('Joint à l\'alarme : ', $('<span>').text(siaDC09_mediaWhat(cfg)))
    addLine('Réception : ', $('<span>').text(ftps ? 'copie déposée sur un serveur FTPS' : 'adresse (URL) dans le message d\'alarme'))
    if (ftps) {
      addLine('Serveur FTPS : ', $('<span>').text((cfg.ftps_host || '') + ':' + (cfg.ftps_port || 21)))
      addLine('Utilisateur : ', $('<span>').text(cfg.ftps_user || ''))
      addLine('Dossier : ', $('<span>').text(cfg.ftps_folder || 'dossier racine'))
      var fp = (cfg.ftps_cert_fingerprint || '').trim()
      addLine('Certificat : ', $('<span>').text(fp ? 'auto-signé (' + fp.substring(0, 11) + '...)' : 'reconnu'))
    } else {
      addLine('Serveur Frigate : ', cfg.frigate_media_url_template
        ? $('<span>').text(cfg.frigate_media_url_template)
        : $('<em class="text-muted">').text('non configurée'))
    }
  }

  // Zones summary (labels denormalized in sia_zone_mappings at save time)
  var $zones = $('#siaDC09-summary-zones').empty()
  var mappings = cfg.sia_zone_mappings || []
  if (typeof mappings === 'string') {
    try { mappings = JSON.parse(mappings) } catch(e) { mappings = [] }
  }
  if (mappings.length === 0) {
    $('<em>').text('Aucune zone configurée').appendTo($zones)
  } else {
    mappings.forEach(function(m) {
      var $row = $('<div>')
      // Prefix with the number transmitted to the CSR, so config mode shows what it receives.
      if (m.zone_number) {
        $row.append($('<strong>').text('N° ' + m.zone_number + ' '))
      }
      $row.append($('<span>').text(m.zone_name))
      if (m.frigate_camera_label) {
        $row.append($('<span>').text(' → '))
        $row.append($('<i class="fas fa-camera" style="margin-right:3px;">'))
        $row.append($('<span>').text(m.frigate_camera_label))
      } else {
        $row.append($('<span class="text-muted">').text(' → (aucune caméra)'))
      }
      $row.appendTo($zones)
    })
  }

  // Notification summary
  var $notify = $('#siaDC09-summary-notify').empty()
  var notifyLabel = siaDC09_notifyTargetLabel(cfg)
  if (notifyLabel) {
    $('<span>').text(notifyLabel).appendTo($notify)
  } else {
    $('<em>').text('Non configuré').appendTo($notify)
  }
}

// Human-readable notification target, or '' when step 3 left nothing usable.
function siaDC09_notifyTargetLabel(cfg) {
  if (cfg.sia_notify_kind !== 'internal') {
    return cfg.sia_notify_cmd_human || ''
  }

  if (cfg.sia_notify_internal === 'message') {
    return 'Centre de messages Jeedom'
  }
  if (cfg.sia_notify_internal === 'scenario') {
    // Read the label off the <select> rendered server-side rather than building it here.
    var scenarioName = $('#siaDC09_notifyScenario option')
      .filter(function() { return this.value === String(cfg.sia_notify_scenario_id) })
      .text()
    return scenarioName ? 'Scénario : ' + scenarioName : ''
  }
  return ''
}

// ===== COMMAND TABLE =====

function addCmdToTable(_cmd) {
  if (!isset(_cmd)) {
    var _cmd = { configuration: {} }
  }
  if (!isset(_cmd.configuration)) {
    _cmd.configuration = {}
  }
  var tr = '<tr class="cmd" data-cmd_id="' + init(_cmd.id) + '">'
  tr += '<td class="hidden-xs"><span class="cmdAttr" data-l1key="id"></span></td>'
  tr += '<td><div class="input-group">'
  tr += '<input class="cmdAttr form-control input-sm roundedLeft" data-l1key="name" placeholder="{{Nom}}">'
  tr += '<span class="input-group-btn"><a class="cmdAction btn btn-sm btn-default" data-l1key="chooseIcon" title="{{Icône}}"><i class="fas fa-icons"></i></a></span>'
  tr += '<span class="cmdAttr input-group-addon roundedRight" data-l1key="display" data-l2key="icon" style="font-size:19px;padding:0 5px 0 0!important;"></span>'
  tr += '</div></td>'
  tr += '<td><span class="type" type="' + init(_cmd.type) + '">' + jeedom.cmd.availableType() + '</span>'
  tr += '<span class="subType" subType="' + init(_cmd.subType) + '"></span></td>'
  tr += '<td>'
  tr += '<label class="checkbox-inline"><input type="checkbox" class="cmdAttr" data-l1key="isVisible" checked/>{{Afficher}}</label> '
  tr += '<label class="checkbox-inline"><input type="checkbox" class="cmdAttr" data-l1key="isHistorized" checked/>{{Historiser}}</label>'
  tr += '</td>'
  tr += '<td><span class="cmdAttr" data-l1key="htmlstate"></span></td>'
  tr += '<td>'
  if (is_numeric(_cmd.id)) {
    tr += '<a class="btn btn-default btn-xs cmdAction" data-action="configure"><i class="fas fa-cogs"></i></a> '
    tr += '<a class="btn btn-default btn-xs cmdAction" data-action="test"><i class="fas fa-rss"></i> {{Tester}}</a>'
  }
  tr += '<i class="fas fa-minus-circle pull-right cmdAction cursor" data-action="remove" title="{{Supprimer}}"></i></td>'
  tr += '</tr>'
  $('#table_cmd tbody').append(tr)
  var tr = $('#table_cmd tbody tr').last()
  jeedom.eqLogic.buildSelectCmd({
    id: $('.eqLogicAttr[data-l1key=id]').value(),
    filter: { type: 'info' },
    error: function(error) {
      $('#div_alert').showAlert({ message: error.message, level: 'danger' })
    },
    success: function(result) {
      tr.find('.cmdAttr[data-l1key=value]').append(result)
      tr.setValues(_cmd, '.cmdAttr')
      jeedom.cmd.changeType(tr, init(_cmd.subType))
    }
  })
}

// ===== DIAGNOSTIC TAB =====

// Header cards mirror the dashboard widget (core/template/dashboard/siaDC09.html):
// the logic below is a copy of its SM1/SM2 rendering, kept in step by hand.
var _siaDC09_COLOR_CLASSES = 'text-success text-warning text-danger text-muted'

// supervision_state: 2=OK 1=degraded 0=lost (unknown falls back to degraded)
var _siaDC09_stateClasses = {
  2: 'text-success',
  1: 'text-warning',
  0: 'text-danger'
}

// supervision_state is 0/1/2 only, so the icon is chosen from the label text
// (daemon.py _supervision_label()); the state only gives the color.
var _siaDC09_SM1_ICONS = [
  { re: /dégradée/i,       icon: 'fa-exclamation-triangle' },
  { re: /initialisation/i, icon: 'fa-spinner fa-pulse' },
  { re: /^connexion ok/i,  icon: 'fa-check-circle' },
  { re: /perdue/i,         icon: 'fa-unlink' },
  { re: /reconnexion/i,    icon: 'fa-sync-alt fa-spin' },
  { re: /hors réseau/i,    icon: 'fa-plug' },
  { re: /clé/i,            icon: 'fa-key' },
  { re: /arrêté/i,         icon: 'fa-stop-circle' },
  { re: /désactivé/i,      icon: 'fa-pause-circle', cls: 'text-muted' }
]
var _siaDC09_SM1_FALLBACK = {
  'text-success': 'fa-check-circle',
  'text-warning': 'fa-exclamation-triangle',
  'text-danger': 'fa-times-circle',
  'text-muted': 'fa-question-circle'
}

// event_label is "{Type} (zone N|utilisateur N) : {état}" (daemon.py _event_label_from_sm2()).
var _siaDC09_SM2_TYPES = {
  'intrusion': 'fa-user-secret', 'incendie': 'fa-fire', 'panique': 'fa-bell',
  'armement': 'fa-lock', 'désarmement': 'fa-lock-open', 'annulation': 'fa-undo', 'test cyclique': 'fa-heartbeat'
}
var _siaDC09_SM2_TYPE_COLORS = {
  'intrusion': 'text-danger', 'incendie': 'text-danger', 'panique': 'text-danger',
  'désarmement': 'text-warning', 'armement': 'text-success', 'annulation': 'text-warning', 'test cyclique': 'text-muted'
}
var _siaDC09_SM2_STATUS = [
  { re: /en cours/i,       icon: 'fa-spinner fa-pulse', cls: 'text-warning' },
  { re: /confirm/i,        icon: 'fa-check-circle',     cls: '' },
  { re: /refus/i,          icon: 'fa-ban',              cls: 'text-danger' },
  { re: /sans réponse/i,   icon: 'fa-times-circle',     cls: 'text-danger' },
  { re: /non transmise/i,  icon: 'fa-key',              cls: 'text-danger' }
]

function siaDC09_pad2(n) { return String(n).padStart(2, '0') }

function siaDC09_sameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

// Accepts ISO 8601 ("2026-05-18T14:32:11+02:00", daemon) and Jeedom dates
// ("2026-05-18 14:32:11", local time). Returns ms, or NaN when unusable.
function siaDC09_parseDate(s) {
  if (!s) return NaN
  var str = String(s)
  return new Date(str.indexOf('T') >= 0 ? str : str.replace(/-/g, '/')).getTime()
}

// Same as the widget's formatTime(): relative while recent (with the precise clock
// time appended), absolute with seconds once older than today. Local time.
function siaDC09_formatTime(ms, nowMs) {
  var d = new Date(ms), now = new Date(nowMs), diff = nowMs - ms
  var hhmmss = siaDC09_pad2(d.getHours()) + ':' + siaDC09_pad2(d.getMinutes()) + ':' + siaDC09_pad2(d.getSeconds())
  if (diff < 60000) return "à l'instant · " + hhmmss
  if (diff < 3600000) return 'il y a ' + Math.floor(diff / 60000) + ' min · ' + hhmmss
  if (siaDC09_sameDay(d, now)) return 'il y a ' + Math.floor(diff / 3600000) + ' h · ' + hhmmss
  if (siaDC09_sameDay(d, new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1))) return 'hier ' + hhmmss
  return siaDC09_pad2(d.getDate()) + '/' + siaDC09_pad2(d.getMonth() + 1) + ' ' + hhmmss
}

function siaDC09_colorize($el, cls) {
  $el.removeClass(_siaDC09_COLOR_CLASSES)
  if (cls) $el.addClass(cls)
}

function siaDC09_initDiagnosticTab(wizardStep) {
  if (wizardStep >= 4) {
    $('#siaDC09_diagnosticTabLi').show()
  } else {
    $('#siaDC09_diagnosticTabLi').hide()
  }
}

function siaDC09_loadDiagnosticData() {
  $.ajax({
    type: 'POST',
    url: 'plugins/siaDC09/core/ajax/siaDC09.ajax.php',
    data: { action: 'getDiagnosticData', ajax: 1 },
    dataType: 'json',
    global: false,
    success: function(data) {
      var result = data.result || {}
      siaDC09_renderBadge(result.supervision_state, result.supervision_label, result.state_date)
      siaDC09_renderEventBadge(result.event_state, result.event_label, result.event_date)
      siaDC09_renderErrors(result.errors || [])
      siaDC09_renderMessages(result.messages || [])
    },
    error: function() {
      $('#div_alert').showAlert({ message: '{{Erreur lors du chargement des données de diagnostic}}', level: 'danger' })
    }
  })
}

function siaDC09_setHeaderTime(selector, dateStr, show, prefix) {
  var ms = siaDC09_parseDate(dateStr)
  $(selector).text((show && !isNaN(ms)) ? (prefix || '') + siaDC09_formatTime(ms, Date.now()) : '')
}

// SM1 card: icon in a ring colored by the state, label, "N échecs sur 3", last-update time.
function siaDC09_renderBadge(supervisionState, supervisionLabel, stateDate) {
  var s = parseInt(supervisionState, 10)
  var cls = _siaDC09_stateClasses[isNaN(s) ? 1 : s] || _siaDC09_stateClasses[1]
  var labelRaw = supervisionLabel || ''
  var entry = null
  for (var i = 0; i < _siaDC09_SM1_ICONS.length; i++) {
    if (_siaDC09_SM1_ICONS[i].re.test(labelRaw)) { entry = _siaDC09_SM1_ICONS[i]; break }
  }
  var icon = entry ? entry.icon : _siaDC09_SM1_FALLBACK[cls]
  if (entry && entry.cls) cls = entry.cls
  var text = labelRaw, sub = ''
  var m = /^(.*?)\s*\((\d+)\/(\d+)\)\s*$/.exec(labelRaw)
  if (m) { text = m[1]; sub = m[2] + (m[2] === '1' ? ' échec sur ' : ' échecs sur ') + m[3] }
  siaDC09_colorize($('#siaDC09_badge'), cls)
  $('#siaDC09_badgeIcon').attr('class', 'fas ' + icon)
  $('#siaDC09_badgeLabel').text(text)
  $('#siaDC09_badgeSub').text(sub).css('display', sub ? 'block' : 'none')
  siaDC09_setHeaderTime('#siaDC09_badgeTime', stateDate, true)
}

// SM2 card ("Dernier événement"): type/zone head and status line, colored like the widget.
function siaDC09_renderEventBadge(eventState, eventLabel, eventDate) {
  var raw = eventLabel || ''
  var idx = raw.indexOf(' : ')
  var st = null
  if (idx >= 0) {
    var statusTxt = raw.slice(idx + 3)
    for (var i = 0; i < _siaDC09_SM2_STATUS.length; i++) {
      if (_siaDC09_SM2_STATUS[i].re.test(statusTxt)) { st = _siaDC09_SM2_STATUS[i]; break }
    }
  }
  var $statusText = $('#siaDC09_eventBadgeLabel')
  var $statusIcon = $('#siaDC09_eventStatusIcon')
  var $head = $('#siaDC09_eventHead')
  var typeCls = 'text-muted'
  var typeName = '', m = null
  if (st) {
    var head = raw.slice(0, idx)
    m = /^(.*?)\s*\((zone|utilisateur)\s+(.+?)\)\s*$/i.exec(head)
    typeName = m ? m[1] : head
    typeCls = _siaDC09_SM2_TYPE_COLORS[typeName.toLowerCase()] || st.cls || 'text-muted'
  }
  siaDC09_colorize($('#siaDC09_eventBar'), typeCls)
  siaDC09_colorize($('#siaDC09_eventTypeWrap'), typeCls)
  siaDC09_colorize($statusText, st ? st.cls : 'text-muted')
  if (!st) {
    // Idle ("Inactif", "Aucun événement…") or an unknown text: discreet raw line.
    $head.css('display', 'none')
    $statusIcon.css('display', 'none')
    $statusText.text(raw).css('opacity', '0.6')
    siaDC09_setHeaderTime('#siaDC09_eventTime', eventDate, false)
    return
  }
  $('#siaDC09_eventTypeText').text(typeName)
  $('#siaDC09_eventWhere').text(m ? m[2] + ' ' + m[3] : '')
  $('#siaDC09_eventTypeIcon').attr('class', 'fas ' + (_siaDC09_SM2_TYPES[typeName.toLowerCase()] || 'fa-bell'))
  $head.css('display', 'flex')
  $statusIcon.attr('class', 'fas ' + st.icon).css('display', '')
  siaDC09_colorize($statusIcon, st.cls)
  $statusText.text(raw.slice(idx + 3)).css('opacity', '')
  siaDC09_setHeaderTime('#siaDC09_eventTime', eventDate, true, ' · ')
}

function siaDC09_renderErrors(errors) {
  var $list = $('#siaDC09_errorsList').empty()
  if (!errors || errors.length === 0) {
    $list.html('<em class="text-muted">{{Aucune erreur enregistrée}}</em>')
    return
  }
  var $table = $('<table class="table table-condensed table-striped" style="margin-bottom:0;">')
  errors.forEach(function(err) {
    var $tr = $('<tr>')
    var ts = siaDC09_formatTimestamp(err.timestamp)
    $tr.append($('<td style="vertical-align:top;white-space:nowrap;">').text(ts))
    $tr.append($('<td style="vertical-align:top;">').text(err.code || ''))
    $tr.append($('<td style="vertical-align:top;">').text(err.message || ''))
    $table.append($tr)
  })
  $list.append($table)
}

// ISO 8601 -> widget-style local time (see siaDC09_formatTime). nowMs is injectable for tests.
function siaDC09_formatTimestamp(isoString, nowMs) {
  var ms = siaDC09_parseDate(isoString)
  if (isNaN(ms)) return ''
  return siaDC09_formatTime(ms, nowMs === undefined ? Date.now() : nowMs)
}

// Diagnostic tab shown event — load data on first activation
// Delegated binding handles the case where the tab anchor is injected after script parse
$(document).on('shown.bs.tab', 'a[href="#diagnosticTab"]', function() {
  siaDC09_loadDiagnosticData()
})

// Actualiser button (errors panel)
$('#siaDC09_errorsRefresh').on('click', function() {
  var $btn = $(this)
  if ($btn.attr('disabled')) return
  $btn.attr('disabled', true)
  siaDC09_loadDiagnosticData()
  setTimeout(function() { $btn.removeAttr('disabled') }, 2000)
})

// Actualiser button (inspector panel)
$('#siaDC09_inspectorRefresh').on('click', function() {
  var $btn = $(this)
  if ($btn.attr('disabled')) return
  $btn.attr('disabled', true)
  siaDC09_loadDiagnosticData()
  setTimeout(function() { $btn.removeAttr('disabled') }, 2000)
})

// Vider button (errors panel)
$('#siaDC09_errorsClear').on('click', function() {
  var $btn = $(this)
  if ($btn.attr('disabled')) return
  $btn.attr('disabled', true)
  $.ajax({
    type: 'POST',
    url: 'plugins/siaDC09/core/ajax/siaDC09.ajax.php',
    data: { action: 'clearDiagnosticData', target: 'errors', ajax: 1 },
    dataType: 'json',
    global: false,
    success: function() {
      $('#siaDC09_errorsList').html('<em class="text-muted">{{Aucune erreur enregistrée}}</em>')
      $btn.removeAttr('disabled')
    },
    error: function() {
      $btn.removeAttr('disabled')
      $('#div_alert').showAlert({ message: '{{Erreur lors de la suppression}}', level: 'danger' })
    }
  })
})

// Vider button (inspector panel)
$('#siaDC09_inspectorClear').on('click', function() {
  var $btn = $(this)
  if ($btn.attr('disabled')) return
  $btn.attr('disabled', true)
  $.ajax({
    type: 'POST',
    url: 'plugins/siaDC09/core/ajax/siaDC09.ajax.php',
    data: { action: 'clearDiagnosticData', target: 'messages', ajax: 1 },
    dataType: 'json',
    global: false,
    success: function() {
      _siaDC09_decodeCache = {}
      $('#siaDC09_inspectorList').html('<em class="text-muted">{{Aucun échange SIA enregistré}}</em>')
      $btn.removeAttr('disabled')
    },
    error: function() {
      $btn.removeAttr('disabled')
      $('#div_alert').showAlert({ message: '{{Erreur lors de la suppression}}', level: 'danger' })
    }
  })
})

// ===== Protocol Inspector — Message Rendering (Story 9-2) =====

// Cache for decoded frame results: key = hex string, value = decoded object
var _siaDC09_decodeCache = {}

// What each frame/event code means, shown on the row. NULL = supervision frame.
var _siaDC09_codeExplain = {
  'NULL': 'Contrôle de liaison (supervision)',
  'BA': 'Alarme intrusion',
  'FA': 'Alarme incendie',
  'PA': 'Alarme panique',
  'BC': "Annulation d'alarme",
  'OP': 'Désarmement (ouverture)',
  'CL': 'Armement (fermeture)',
  'RP': 'Test cyclique'
}

// Alarm transitions (daemon.py _log_sm2_event) that mean "sent again".
var _siaDC09_retryTransitions = ['failed_timeout', 'nak_retry']

// Kind label of an inspector row. routine = healthy supervision exchange, événement =
// alarm frame, retry = alarm frame sent again, incident = supervision timeout/NAK or
// an alarm that ended in failure.
function siaDC09_messageKind(msg) {
  if (msg.routine === 1) return { text: '{{routine}}', cls: 'label-default' }
  if (msg.dialog_type !== 'alarm') return { text: '{{incident}}', cls: 'label-danger' }
  var tr = msg.transition || ''
  if (_siaDC09_retryTransitions.indexOf(tr) >= 0) return { text: '{{retry}}', cls: 'label-warning' }
  if (tr.indexOf('failed') === 0) return { text: '{{incident}}', cls: 'label-danger' }
  return { text: '{{événement}}', cls: 'label-success' }
}

// Task 4: Build collapsed message rows
function siaDC09_renderMessages(messages) {
  var $list = $('#siaDC09_inspectorList').empty()
  if (!messages || messages.length === 0) {
    $list.html('<em class="text-muted">{{Aucun échange SIA enregistré}}</em>')
    return
  }
  messages.forEach(function(msg) {
    var ts = siaDC09_formatTimestamp(msg.timestamp)
    var elapsedMs = msg.elapsed_ms || 0

    var kind = siaDC09_messageKind(msg)

    // Direction icon (sent = →, received back in response = both directions shown as →)
    var direction = '<span style="font-family:monospace;">&#8594;</span>'

    var requestHex = msg.request_hex || ''
    var responseHex = msg.response_hex || ''

    var $row = $('<div class="sia-msg-row">')
      .attr('data-request-hex', requestHex)
      .attr('data-response-hex', responseHex)
      .css({ cursor: 'pointer', padding: '6px 10px', borderBottom: '1px solid #eee' })

    // The frame/event code (BA, RP, OP...) is what tells rows apart; the wire ID token
    // is almost always SIA-DCS or NULL. Supervision frames and unreadable (encrypted)
    // ones carry no code and show NULL.
    var code = msg.event_code || 'NULL'
    var seqStr = msg.sequence !== undefined ? ('#' + ('0000' + msg.sequence).slice(-4)) : ''
    var accountStr = msg.account ? ('#' + msg.account) : ''

    $row.append(direction + ' ')
    $row.append($('<span class="sia-token label label-default" style="margin-right:4px;">').text(code))
    $row.append($('<span class="sia-seq text-muted" style="margin-right:4px; font-family:monospace;">').text(seqStr))
    $row.append($('<span class="sia-account text-muted" style="margin-right:6px; font-family:monospace;">').text(accountStr))
    $row.append($('<span class="sia-explain text-muted" style="margin-right:6px;">').text(_siaDC09_codeExplain[code] || ''))
    $row.append($('<span class="sia-kind label ' + kind.cls + '" style="margin-right:6px;">').text(kind.text))
    $row.append($('<span class="sia-delay" style="margin-right:6px;">').text(elapsedMs + 'ms'))
    $row.append($('<span class="sia-time pull-right text-muted">').text(ts))

    var $detail = $('<div class="sia-msg-detail">').css({ display: 'none' })
    $row.after($detail)

    $list.append($row).append($detail)

    // Store reference on row for expand handler
    $row.data('detail', $detail)
    $row.data('msg', msg)
  })
}

// Task 5: Expand/collapse with field table
$('#siaDC09_inspectorList').on('click', '.sia-msg-row', function() {
  var $row = $(this)
  var $detail = $row.data('detail')
  if (!$detail) {
    // detail div is right after row in DOM
    $detail = $row.next('.sia-msg-detail')
  }
  if (!$detail || !$detail.length) return

  if ($detail.is(':visible')) {
    $detail.hide()
    return
  }

  // Already decoded — show cached result
  var requestHex = $row.attr('data-request-hex') || ''
  var cacheKey = requestHex + '|' + ($row.attr('data-response-hex') || '')
  if (_siaDC09_decodeCache[cacheKey]) {
    siaDC09_renderFrameDetail($detail, $row.data('msg'), _siaDC09_decodeCache[cacheKey], requestHex, $row.attr('data-response-hex') || '')
    $detail.show()
    return
  }

  if (!requestHex) {
    $detail.html('<div style="padding:8px 10px;"><em class="text-muted">{{Pas de données hexadécimales disponibles}}</em></div>').show()
    return
  }

  $detail.html('<div style="padding:8px 10px;"><em class="text-muted">{{Décodage en cours…}}</em></div>').show()

  $.ajax({
    type: 'POST',
    url: 'plugins/siaDC09/core/ajax/siaDC09.ajax.php',
    data: { action: 'decodeFrame', hex: requestHex, ajax: 1 },
    dataType: 'json',
    global: false,
    success: function(data) {
      if (data.state === 'error') {
        var errMsg = (typeof data.result === 'string') ? data.result : '{{Erreur de décodage}}'
        $detail.html('<div style="padding:8px 10px;color:#d9534f;">' + $('<span>').text(errMsg).html() + '</div>')
        return
      }
      var decoded = data.result || {}
      _siaDC09_decodeCache[cacheKey] = decoded
      siaDC09_renderFrameDetail($detail, $row.data('msg'), decoded, requestHex, $row.attr('data-response-hex') || '')
    },
    error: function(xhr) {
      var msg = (xhr.responseJSON && xhr.responseJSON.error) ? xhr.responseJSON.error : '{{Erreur de décodage}}'
      $detail.html('<div style="padding:8px 10px;color:#d9534f;">' + $('<span>').text(msg).html() + '</div>')
    }
  })
})

function siaDC09_renderFrameDetail($detail, msg, decoded, requestHex, responseHex) {
  $detail.empty().css({ padding: '10px 10px 10px 25px', background: '#f9f9f9', borderBottom: '1px solid #ddd' })

  var isAlarm = msg && msg.dialog_type === 'alarm'
  var attempts = (msg && msg.attempts) ? msg.attempts : null

  // If alarm with multiple attempts — render attempt sub-blocks
  if (isAlarm && attempts && attempts.length > 1) {
    attempts.forEach(function(attempt, idx) {
      var $block = $('<div class="sia-attempt" style="margin-bottom:10px;">')
      $block.append($('<div style="font-weight:bold;margin-bottom:4px;">').text('Tentative ' + (idx + 1) + '/' + attempts.length))
      var attemptReqHex = attempt.request_hex || requestHex
      var attemptResHex = attempt.response_hex || ''
      var elapsedText = attempt.elapsed_ms ? attempt.elapsed_ms + 'ms' : ''
      $block.append(siaDC09_buildHexButtons(attemptReqHex, attemptResHex))
      if (idx === attempts.length - 1) {
        // Decoded data shown on last attempt
        $block.append(siaDC09_buildFieldTable(decoded))
      }
      if (elapsedText) $block.append($('<div class="text-muted" style="font-size:11px;margin-top:3px;">').text(elapsedText))
      $detail.append($block)
    })
    return
  }

  // Single frame detail
  $detail.append(siaDC09_buildHexButtons(requestHex, responseHex))
  $detail.append(siaDC09_buildFieldTable(decoded))
}

function siaDC09_buildHexButtons(requestHex, responseHex) {
  var $div = $('<div style="margin-bottom:8px;">')
  if (requestHex) {
    var $btn = $('<button class="btn btn-xs btn-default sia-copy-hex" style="margin-right:4px;">')
      .attr('data-hex', requestHex)
      .text('{{Copier hex (envoyé)}}')
    $div.append($btn)
  }
  if (responseHex) {
    var $btn2 = $('<button class="btn btn-xs btn-default sia-copy-hex" style="margin-right:4px;">')
      .attr('data-hex', responseHex)
      .text('{{Copier hex (reçu)}}')
    $div.append($btn2)
  }
  return $div
}

function siaDC09_buildFieldTable(decoded) {
  var $wrap = $('<div>')

  // Encryption indicator
  if (decoded.encrypted) {
    var encLabel = decoded.data_decrypted
      ? '<span class="label label-info" style="margin-bottom:6px;display:inline-block;">Chiffrement AES-128-CBC (déchiffré)</span>'
      : '<span class="label label-warning" style="margin-bottom:6px;display:inline-block;">Chiffrement AES-128-CBC (non déchiffré)</span>'
    $wrap.append($(encLabel))
  }

  var $table = $('<table class="table table-condensed table-bordered" style="margin-bottom:5px;">')
  var $thead = $('<thead>').append($('<tr>').append($('<th>').text('Champ')).append($('<th>').text('Valeur')))
  var $tbody = $('<tbody>')
  $table.append($thead).append($tbody)

  function addRow(label, value, hint) {
    var $tr = $('<tr>')
    $tr.append($('<td>').text(label))
    var $td = $('<td>')
    if (value !== null && value !== undefined && value !== '') {
      $td.append($('<code>').text(String(value)))
    } else {
      $td.append($('<em class="text-muted">').text('—'))
    }
    if (hint) $td.append($('<div class="sia-hint text-muted" style="font-size:11px;">').text(hint))
    $tbody.append($tr.append($td))
  }

  addRow('ID Token', decoded.id_token,
    'Type de trame : SIA-DCS = événement, NULL = supervision ; le préfixe * indique des données chiffrées.')
  addRow('Séquence', decoded.sequence)
  addRow('Préfixe récepteur', decoded.receiver_prefix || '—')
  addRow('Préfixe compte', decoded.account_prefix)
  addRow('Compte', decoded.account)
  addRow('Données (brut)', decoded.data_raw)
  if (decoded.encrypted && decoded.data_decrypted !== null && decoded.data_decrypted !== undefined) {
    addRow('Données (déchiffré)', decoded.data_decrypted)
  }
  if (decoded.extended_fields && Object.keys(decoded.extended_fields).length > 0) {
    addRow('Champs étendus', JSON.stringify(decoded.extended_fields))
  }
  if (decoded.timestamp_str) {
    addRow('Horodatage', decoded.timestamp_str)
  }

  // CRC row
  var $crcValue = $('<span>')
  var $crcIcon = $('<span>').css('color', decoded.crc_valid ? '#5cb85c' : '#d9534f')
    .text(decoded.crc_valid ? '✓ CRC valide' : '✗ CRC invalide')
  $crcValue.append($crcIcon)
  $crcValue.append(document.createTextNode(' (reçu: 0x' + (decoded.crc_received || '') + ', calculé: 0x' + (decoded.crc_computed || '') + ')'))
  var $crcTr = $('<tr>').append($('<td>').text('CRC')).append($('<td>').append($crcValue))
  $tbody.append($crcTr)

  addRow('Longueur', 'déclarée: ' + decoded.length_declared + ' / réelle: ' + decoded.length_actual)
  addRow('Format CRC', decoded.crc_format)

  $wrap.append($table)
  return $wrap
}

// Task 6: Clipboard copy button handler
$(document).on('click', '.sia-copy-hex', function() {
  var $btn = $(this)
  var hex = $btn.attr('data-hex') || ''
  if (!hex) return

  var originalText = $btn.text()
  var copyDone = function() {
    $btn.text('{{Copié !}}')
    setTimeout(function() { $btn.text(originalText) }, 1500)
  }

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(hex).then(copyDone).catch(function() {
      siaDC09_copyHexFallback(hex, copyDone)
    })
  } else {
    siaDC09_copyHexFallback(hex, copyDone)
  }
})

function siaDC09_copyHexFallback(hex, onDone) {
  var $ta = $('<textarea>').val(hex).css({ position: 'fixed', top: '-9999px', left: '-9999px' })
  $('body').append($ta)
  $ta[0].select()
  try { document.execCommand('copy') } catch (e) {}
  $ta.remove()
  if (onDone) onDone()
}
