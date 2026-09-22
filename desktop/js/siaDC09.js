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
  var wizardStep = parseInt(_eqLogic.configuration && _eqLogic.configuration.sia_wizard_step || 0)
  siaDC09_initDiagnosticTab(wizardStep)
  if (wizardStep >= 4) {
    $('#siaDC09-wizard').hide()
    $('#siaDC09-config-summary').show()
    siaDC09_populateConfigSummary(_eqLogic)
  } else {
    $('#siaDC09-wizard').show()
    $('#siaDC09-config-summary').hide()
    var step = Math.max(1, wizardStep)
    siaDC09_showStep(step)
  }
  // Restore card selection state
  var provider = _eqLogic.configuration && _eqLogic.configuration.csr_provider || ''
  siaDC09_selectCard(provider)
}

function saveEqLogic(_eqLogic) {
  var step = siaDC09_currentStep()
  if (step === 3) {
    var mappings = []
    $('#siaDC09-zone-tbody tr').each(function() {
      var zoneName = $(this).attr('data-zone-name')
      // The row keeps the number it was displayed with — never recomputed here, so a number
      // already declared to the CSR stays attached to the same zone.
      var zoneNumber = parseInt($(this).attr('data-zone-number'), 10)
      var $takeSelect = $(this).find('.siaDC09-zone-camera-take')
      var $urlSelect = $(this).find('.siaDC09-zone-media-url')
      var cameraActionCmdId = $takeSelect.val() || null
      var mediaUrlCmdId = $urlSelect.val() || null
      mappings.push({
        zone_number: zoneNumber || null,
        zone_name: zoneName,
        camera_action_cmd_id: cameraActionCmdId ? parseInt(cameraActionCmdId) : null,
        camera_action_cmd_label: cameraActionCmdId ? $takeSelect.find(':selected').text() : null,
        media_url_cmd_id: mediaUrlCmdId ? parseInt(mediaUrlCmdId) : null,
        media_url_cmd_label: mediaUrlCmdId ? $urlSelect.find(':selected').text() : null
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

function siaDC09_showStep(step) {
  $('.siaDC09-step').hide()
  $('#siaDC09-step' + step).show()

  if (step === 1) {
    siaDC09_applyReadonly()
  }
  if (step === 2) {
    siaDC09_populateStep2Summary()
    siaDC09_runConnectionTest()
  }
  if (step === 3) {
    var eqLogic = $('.eqLogic').getValues('.eqLogicAttr')[0]
    siaDC09_loadZoneData(eqLogic)
  }
  if (step === 4) {
    siaDC09_initNotifyTarget()
  }
}

function siaDC09_setWizardStep(step) {
  $('.eqLogicAttr[data-l2key="sia_wizard_step"]').val(step)
}

// ===== STEP 1: PRESET CARD SELECTION =====

function siaDC09_selectCard(provider) {
  $('.siaDC09-preset-card').removeClass('panel-primary').addClass('panel-default')
  if (provider === 'ima_protect') {
    $('#card-ima-protect').removeClass('panel-default').addClass('panel-primary')
    $('#siaDC09-personnaliser-row').show()
    siaDC09_fillFromPreset()
    siaDC09_applyReadonly()
  } else if (provider === 'manual') {
    $('#card-manual').removeClass('panel-default').addClass('panel-primary')
    $('#siaDC09-personnaliser-row').hide()
    siaDC09_removeReadonly()
  } else {
    $('#siaDC09-personnaliser-row').hide()
  }
}

function siaDC09_fillFromPreset() {
  var $card = $('#card-ima-protect')
  var fields = ['csr_ip', 'csr_port', 'transport', 'encryption_enabled', 'supervision_interval', 'retry_count', 'reconnect_delay']
  fields.forEach(function(key) {
    var val = $card.data('preset-' + key)
    if (val !== undefined) {
      var $field = $('.eqLogicAttr[data-l2key="' + key + '"]')
      if ($field.is(':checkbox')) {
        $field.prop('checked', val === '1' || val === true || val === 1)
      } else {
        $field.val(String(val))
      }
    }
  })
}

function siaDC09_applyReadonly() {
  var provider = $('.eqLogicAttr[data-l2key="csr_provider"]').val()
  if (provider && provider !== 'manual') {
    $('.siaDC09-csr-field').each(function() {
      var $f = $(this)
      if ($f.is(':checkbox')) {
        $f.on('click.presetLock', function(e) { e.preventDefault() })
      } else if ($f.is('select')) {
        $f.prop('disabled', true)
      } else {
        $f.attr('readonly', true)
      }
    })
  }
}

function siaDC09_removeReadonly() {
  $('.siaDC09-csr-field').each(function() {
    var $f = $(this)
    $f.removeAttr('readonly').prop('disabled', false).off('click.presetLock')
  })
}

// Card click handlers
$('.siaDC09-preset-card').on('click', function() {
  var provider = $(this).data('provider')
  $('.eqLogicAttr[data-l2key="csr_provider"]').val(provider)
  siaDC09_selectCard(provider)
})

// Personnaliser button
$('#bt_personnaliser').on('click', function() {
  $('.eqLogicAttr[data-l2key="csr_provider"]').val('manual')
  siaDC09_selectCard('manual')
})

// ===== STEP 1 VALIDATION =====

function siaDC09_validateStep1() {
  var errors = []
  var accountNumber = $('.eqLogicAttr[data-l2key="account_number"]').val().trim()
  var csrIp = $('.eqLogicAttr[data-l2key="csr_ip"]').val().trim()
  var csrPort = parseInt($('.eqLogicAttr[data-l2key="csr_port"]').val())
  var encEnabled = $('.eqLogicAttr[data-l2key="encryption_enabled"]').is(':checked')
  var encKey = $('.eqLogicAttr[data-l2key="encryption_key"]').val().trim()

  if (!accountNumber || !/^[0-9a-fA-F]{3,16}$/.test(accountNumber)) {
    errors.push('{{Numéro de compte : 3 à 16 caractères hexadécimaux requis}}')
  }
  if (!csrIp || csrIp === 'TBD') {
    errors.push("{{Adresse IP de la centrale requise}}")
  }
  if (isNaN(csrPort) || csrPort < 1 || csrPort > 65535) {
    errors.push('{{Port : nombre entre 1 et 65535 requis}}')
  }
  if (encEnabled && encKey) {
    if (!/^[0-9a-fA-F]+$/.test(encKey) || [32, 48, 64].indexOf(encKey.length) === -1) {
      errors.push('{{Clé AES : 32, 48 ou 64 caractères hexadécimaux requis}}')
    }
  }
  if (encEnabled && !encKey) {
    errors.push("{{Clé AES requise quand le chiffrement est activé}}")
  }

  if (errors.length > 0) {
    $('#siaDC09-step1-errors').html(errors.join('<br>')).show()
    return false
  }
  $('#siaDC09-step1-errors').hide()
  return true
}

// ===== STEP 1 → STEP 2 ADVANCE =====

$('#bt_step1Next').on('click', function() {
  if ($(this).attr('disabled')) return
  if (!siaDC09_validateStep1()) return

  var $btn = $(this)
  $btn.attr('disabled', true)

  var doAdvance = function() {
    siaDC09_setWizardStep(2)
    // Save then advance — async-safe pattern
    jeedom.eqLogic.save({
      type: 'siaDC09',
      eqLogics: [$('.eqLogic').getValues('.eqLogicAttr')[0]],
      error: function(error) {
        $btn.removeAttr('disabled')
        $('#div_alert').showAlert({ message: error.message, level: 'danger' })
      },
      success: function() {
        siaDC09_showStep(2)
      }
    })
  }

  // Check if daemon is running — warn user
  $.ajax({
    type: 'POST',
    url: 'core/ajax/plugin.ajax.php',
    data: { action: 'deamonInfo', id: 'siaDC09' },
    dataType: 'json',
    global: false,
    success: function(data) {
      if (data.result && data.result.state === 'ok') {
        jeeDialog.confirm('{{Le démon est en cours d\'exécution. Il sera arrêté pour le test. Continuer ?}}', function(result) {
          if (result) {
            doAdvance()
          } else {
            $btn.removeAttr('disabled')
          }
        })
      } else {
        doAdvance()
      }
    },
    error: function() {
      doAdvance()
    }
  })
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
}

function siaDC09_runConnectionTest() {
  _siaDC09_testNakConfirmed = false
  $('#siaDC09-step2-spinner').show()
  $('#siaDC09-step2-result').hide()
  $('#bt_step2Next').attr('disabled', true)
  $('#bt_step2Retest').attr('disabled', true)
  $('#bt_step2Skip').attr('disabled', true)

  $.ajax({
    type: 'POST',
    url: 'plugins/siaDC09/core/ajax/siaDC09.ajax.php',
    data: {
      action: 'testConnection',
      ajax: 1
    },
    dataType: 'json',
    global: false,
    timeout: 35000,
    success: function(data) {
      $('#siaDC09-step2-spinner').hide()
      $('#bt_step2Retest').removeAttr('disabled')
      $('#bt_step2Skip').removeAttr('disabled')

      var result = data.result || {}
      var status = result.status || 'error'
      var detail = result.detail || ''
      var cssClass = ''
      var icon = ''

      if (status === 'ok') {
        cssClass = 'alert-success'
        icon = 'fa-check-circle'
        $('#bt_step2Next').removeAttr('disabled')
      } else if (status === 'nak') {
        cssClass = 'alert-warning'
        icon = 'fa-exclamation-triangle'
        $('#bt_step2Next').removeAttr('disabled')
      } else {
        cssClass = 'alert-danger'
        icon = 'fa-times-circle'
        $('#bt_step2Next').attr('disabled', true)
      }

      var $resultDiv = $('<div class="alert ' + cssClass + '"><i class="fas ' + icon + '"></i> </div>')
      $resultDiv.append($('<span>').text(detail))
      $('#siaDC09-step2-result').empty().append($resultDiv).show()
    },
    error: function(xhr, status, error) {
      $('#siaDC09-step2-spinner').hide()
      $('#bt_step2Retest').removeAttr('disabled')
      $('#bt_step2Skip').removeAttr('disabled')
      $('#siaDC09-step2-result')
        .html('<div class="alert alert-danger"><i class="fas fa-times-circle"></i> {{Erreur de communication avec le serveur}}</div>')
        .show()
    }
  })
}

// Retest button
$('#bt_step2Retest').on('click', function() {
  siaDC09_runConnectionTest()
})

// Ignorer button — advance to step 3 with warning
$('#bt_step2Skip').on('click', function() {
  siaDC09_setWizardStep(3)
  jeedom.eqLogic.save({
    type: 'siaDC09',
    eqLogics: [$('.eqLogic').getValues('.eqLogicAttr')[0]],
    error: function(error) {
      $('#div_alert').showAlert({ message: error.message, level: 'danger' })
    },
    success: function() {
      $('#siaDC09-step3-warning').show()
      siaDC09_showStep(3)
    }
  })
})

// Suivant on Step 2
$('#bt_step2Next').on('click', function() {
  var result = $('#siaDC09-step2-result .alert-warning')
  if (result.length > 0 && !_siaDC09_testNakConfirmed) {
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
      siaDC09_showStep(3)
    }
  })
}

// ===== RESTART WIZARD =====

$('#bt_restartWizard').on('click', function() {
  var doRestart = function() {
    siaDC09_setWizardStep(0)
    jeedom.eqLogic.save({
      type: 'siaDC09',
      eqLogics: [$('.eqLogic').getValues('.eqLogicAttr')[0]],
      error: function(error) {
        $('#div_alert').showAlert({ message: error.message, level: 'danger' })
      },
      success: function() {
        $('#siaDC09-config-summary').hide()
        $('#siaDC09-wizard').show()
        siaDC09_showStep(1)
      }
    })
  }

  // Check daemon running
  $.ajax({
    type: 'POST',
    url: 'core/ajax/plugin.ajax.php',
    data: { action: 'deamonInfo', id: 'siaDC09' },
    dataType: 'json',
    global: false,
    success: function(data) {
      if (data.result && data.result.state === 'ok') {
        jeeDialog.confirm('{{Le démon est en cours d\'exécution. Il sera arrêté. Continuer ?}}', function(result) {
          if (result) {
            doRestart()
          }
        })
      } else {
        doRestart()
      }
    },
    error: function() {
      doRestart()
    }
  })
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
    data: { action: 'getCameraCommands', ajax: 1 },
    dataType: 'json',
    global: false,
    success: function(data) {
      var cameraCommands = data.result || { camera_take: [], camera_url: [] }
      $.ajax({
        type: 'POST',
        url: 'plugins/siaDC09/core/ajax/siaDC09.ajax.php',
        data: { action: 'getZones', ajax: 1 },
        dataType: 'json',
        global: false,
        success: function(data2) {
          var result2 = data2.result || {}
          if (result2.error) {
            $('#siaDC09-step3-nozone').show()
            $('#siaDC09-zone-tbody').empty()
          } else {
            $('#siaDC09-step3-nozone').hide()
            siaDC09_loadZoneTable(result2.zones || [], savedMapping, cameraCommands)
          }
        },
        error: function() {
          $('#siaDC09-step3-nozone').show()
        }
      })
    },
    error: function() {
      // Camera commands failed — still load zones but with empty camera dropdowns
      $.ajax({
        type: 'POST',
        url: 'plugins/siaDC09/core/ajax/siaDC09.ajax.php',
        data: { action: 'getZones', ajax: 1 },
        dataType: 'json',
        global: false,
        success: function(data2) {
          var result2 = data2.result || {}
          if (result2.error) {
            $('#siaDC09-step3-nozone').show()
          } else {
            $('#siaDC09-step3-nozone').hide()
            siaDC09_loadZoneTable(result2.zones || [], savedMapping, { camera_take: [], camera_url: [] })
          }
        },
        error: function() {
          $('#siaDC09-step3-nozone').show()
        }
      })
    }
  })
}

function siaDC09_loadZoneTable(zones, zoneMapping, cameraCommands) {
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
    $tbody.append(siaDC09_buildZoneRow(zoneNumber, zoneName, saved, cameraCommands))
  })
}

function siaDC09_buildZoneRow(zoneNumber, zoneName, saved, cameraCommands) {
  var $tr = $('<tr>')
  $tr.append($('<td>').text(zoneNumber))
  $tr.append($('<td>').text(zoneName))

  // Camera action select (CAMERA_TAKE)
  var $takeSelect = $('<select class="form-control siaDC09-zone-camera-take">')
  $takeSelect.append($('<option value="">').text('(aucune)'))
  ;(cameraCommands.camera_take || []).forEach(function(cmd) {
    var $opt = $('<option>').val(cmd.id).text(cmd.label)
    if (saved.camera_action_cmd_id && String(saved.camera_action_cmd_id) === String(cmd.id)) {
      $opt.prop('selected', true)
    }
    $takeSelect.append($opt)
  })
  $tr.append($('<td>').append($takeSelect))

  // Media URL select (CAMERA_URL)
  var $urlSelect = $('<select class="form-control siaDC09-zone-media-url">')
  $urlSelect.append($('<option value="">').text('(aucune)'))
  ;(cameraCommands.camera_url || []).forEach(function(cmd) {
    var $opt = $('<option>').val(cmd.id).text(cmd.label)
    if (saved.media_url_cmd_id && String(saved.media_url_cmd_id) === String(cmd.id)) {
      $opt.prop('selected', true)
    }
    $urlSelect.append($opt)
  })
  $tr.append($('<td>').append($urlSelect))

  // The displayed <td> is for the user; these attributes are the serialization contract.
  $tr.attr('data-zone-number', zoneNumber)
  $tr.attr('data-zone-name', zoneName)
  return $tr
}

// ===== STEP 3: SUIVANT HANDLER =====

$('#bt_step3Next').on('click', function() {
  if ($(this).attr('disabled')) return
  siaDC09_setWizardStep(4)
  var eqLogic = $('.eqLogic').getValues('.eqLogicAttr')[0]
  eqLogic = saveEqLogic(eqLogic)
  jeedom.eqLogic.save({
    type: 'siaDC09',
    eqLogics: [eqLogic],
    error: function(error) {
      $('#div_alert').showAlert({ message: error.message, level: 'danger' })
    },
    success: function() {
      siaDC09_showStep(4)
    }
  })
})

// ===== STEP 4: NOTIFICATION TARGET =====

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

  $('#siaDC09-step4-error, #siaDC09-step4-error-internal, #siaDC09-step4-error-scenario').hide()
}

// Shows the error that matches the missing field, so the message always names what to fix.
function siaDC09_validateNotifyTarget() {
  $('#siaDC09-step4-error, #siaDC09-step4-error-internal, #siaDC09-step4-error-scenario').hide()

  if ($('#siaDC09_notifyKind').val() !== 'internal') {
    if (!$('.eqLogicAttr[data-l2key="sia_notify_cmd_id"]').val()) {
      $('#siaDC09-step4-error').show()
      return false
    }
    return true
  }

  var internal = $('#siaDC09_notifyInternal').val()
  if (!internal) {
    $('#siaDC09-step4-error-internal').show()
    return false
  }
  if (internal === 'scenario' && !$('#siaDC09_notifyScenario').val()) {
    $('#siaDC09-step4-error-scenario').show()
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
      $('#siaDC09-step4-error').hide()
    }
  )
})

$('#bt_step4Finish').on('click', function() {
  if ($(this).attr('disabled')) return

  if (!siaDC09_validateNotifyTarget()) {
    return
  }

  var $btn = $(this)
  $btn.attr('disabled', true)

  // No saveEqLogic() call needed — step 4 has no zone table; sia_zone_mappings preserved by Jeedom merge
  siaDC09_setWizardStep(4)
  jeedom.eqLogic.save({
    type: 'siaDC09',
    eqLogics: [$('.eqLogic').getValues('.eqLogicAttr')[0]],
    error: function(error) {
      $btn.removeAttr('disabled')
      $('#div_alert').showAlert({ message: error.message, level: 'danger' })
    },
    success: function() {
      // Reload the page — printEqLogic will detect sia_wizard_step=4 and show config mode
      window.location.reload()
    }
  })
})

// ===== CONFIG SUMMARY =====

function siaDC09_populateConfigSummary(eqLogic) {
  var cfg = (eqLogic && eqLogic.configuration) || {}

  // Connection summary
  var provider = cfg.csr_provider === 'ima_protect' ? 'IMA Protect' : 'Personnalisé'
  var $conn = $('#siaDC09-summary-connection').empty()
  $('<div>').append(
    $('<strong>').text('Opérateur : ')
  ).append(
    $('<span>').text(provider)
  ).appendTo($conn)
  $('<div>').append(
    $('<strong>').text('Centrale : ')
  ).append(
    $('<span>').text((cfg.csr_ip || '') + ':' + (cfg.csr_port || '') + ' (' + ((cfg.transport || 'udp').toUpperCase()) + ')')
  ).appendTo($conn)
  $('<div>').append(
    $('<strong>').text('Supervision : ')
  ).append(
    $('<span>').text((cfg.supervision_interval || 60) + 's, ' + (cfg.retry_count || 6) + ' tentatives')
  ).appendTo($conn)
  $('<div>').append(
    $('<strong>').text('Chiffrement : ')
  ).append(
    $('<span>').text(cfg.encryption_enabled ? 'activé' : 'désactivé')
  ).appendTo($conn)

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
      if (m.camera_action_cmd_label) {
        $row.append($('<span>').text(' → '))
        $row.append($('<i class="fas fa-camera" style="margin-right:3px;">'))
        $row.append($('<span>').text(m.camera_action_cmd_label))
      }
      if (m.media_url_cmd_label) {
        $row.append($('<span>').text(' | '))
        $row.append($('<i class="fas fa-link" style="margin-right:3px;">'))
        $row.append($('<span>').text(m.media_url_cmd_label))
      }
      if (!m.camera_action_cmd_id && !m.media_url_cmd_id) {
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

// Human-readable notification target, or '' when step 4 left nothing usable.
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

var _siaDC09_tierMap = {
  'SUPERVISION_TIMEOUT': 'T1',
  'SUPERVISION_NAK': 'T1',
  'BAD_CSR_RESPONSE': 'T2',
  'SUPERVISION_DISCONNECTED': 'T3',
  'EVENT_FAILED': 'T3',
  'TRANSPORT_PERMANENT': 'T3'
}

var _siaDC09_tierClasses = {
  'T1': 'label-info',
  'T2': 'label-warning',
  'T3': 'label-danger'
}

var _siaDC09_badgeColors = {
  2: '#5cb85c',
  1: '#f0ad4e',
  0: '#d9534f'
}

// SM2 event lifecycle: 0=IDLE 1=CONFIRMED 2=FAILED 3=PENDING
var _siaDC09_eventBadgeColors = {
  0: '#777777',
  1: '#5cb85c',
  2: '#d9534f',
  3: '#f0ad4e'
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
      siaDC09_renderBadge(result.supervision_state, result.supervision_label)
      siaDC09_renderEventBadge(result.event_state, result.event_label)
      siaDC09_renderErrors(result.errors || [])
      siaDC09_renderMessages(result.messages || [])
    },
    error: function() {
      $('#div_alert').showAlert({ message: '{{Erreur lors du chargement des données de diagnostic}}', level: 'danger' })
    }
  })
}

function siaDC09_renderStateBadge(dotId, labelId, state, label, colorMap, fallbackKey) {
  var s = parseInt(state, 10)
  if (isNaN(s)) s = fallbackKey
  var color = colorMap[s] || colorMap[fallbackKey]
  $(dotId).css('color', color)
  $(labelId).text(label || '')
}

function siaDC09_renderBadge(supervisionState, supervisionLabel) {
  siaDC09_renderStateBadge('#siaDC09_badgeDot', '#siaDC09_badgeLabel', supervisionState, supervisionLabel, _siaDC09_badgeColors, 1)
}

function siaDC09_renderEventBadge(eventState, eventLabel) {
  siaDC09_renderStateBadge('#siaDC09_eventBadgeDot', '#siaDC09_eventBadgeLabel', eventState, eventLabel, _siaDC09_eventBadgeColors, 0)
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
    $tr.append($('<td style="width:70px;">').text(ts))
    var tier = _siaDC09_tierMap[err.code] || 'T1'
    var tierClass = _siaDC09_tierClasses[tier] || 'label-default'
    $tr.append($('<td style="width:40px;">').html('<span class="label ' + tierClass + '">' + tier + '</span>'))
    $tr.append($('<td>').text(err.code || ''))
    $tr.append($('<td>').text(err.message || ''))
    $table.append($tr)
  })
  $list.append($table)
}

function siaDC09_formatTimestamp(isoString) {
  if (!isoString) return ''
  try {
    var d = new Date(isoString)
    if (isNaN(d.getTime())) return ''
    var h = ('0' + d.getUTCHours()).slice(-2)
    var m = ('0' + d.getUTCMinutes()).slice(-2)
    var s = ('0' + d.getUTCSeconds()).slice(-2)
    return h + ':' + m + ':' + s
  } catch (e) {
    return ''
  }
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

// Task 4: Build collapsed message rows
function siaDC09_renderMessages(messages) {
  var $list = $('#siaDC09_inspectorList').empty()
  if (!messages || messages.length === 0) {
    $list.html('<em class="text-muted">{{Aucun échange SIA enregistré}}</em>')
    return
  }
  messages.forEach(function(msg) {
    var isAlarm = msg.dialog_type === 'alarm'
    var isRoutine = msg.routine === 1
    var ts = siaDC09_formatTimestamp(msg.timestamp)
    var elapsedMs = msg.elapsed_ms || 0

    // Status badge
    var badgeClass = 'label-success'
    var badgeText = elapsedMs + 'ms'
    if (!isRoutine && isAlarm) {
      badgeClass = 'label-warning'
      if (msg.attempts && msg.attempts.length > 1) badgeClass = 'label-danger'
    } else if (!isRoutine) {
      // supervision NAK/timeout
      badgeClass = 'label-warning'
    }

    // Direction icon (sent = →, received back in response = both directions shown as →)
    var direction = '<span style="font-family:monospace;">&#8594;</span>'

    var requestHex = msg.request_hex || ''
    var responseHex = msg.response_hex || ''

    var $row = $('<div class="sia-msg-row">')
      .attr('data-request-hex', requestHex)
      .attr('data-response-hex', responseHex)
      .css({ cursor: 'pointer', padding: '6px 10px', borderBottom: '1px solid #eee' })

    var idToken = msg.id_token ? msg.id_token : (isAlarm ? 'SIA-DCS' : 'NULL')
    var seqStr = msg.sequence !== undefined ? ('#' + ('0000' + msg.sequence).slice(-4)) : ''
    var accountStr = msg.account ? ('#' + msg.account) : ''

    $row.append(direction + ' ')
    $row.append($('<span class="sia-token label label-default" style="margin-right:4px;">').text(idToken))
    $row.append($('<span class="sia-seq text-muted" style="margin-right:4px; font-family:monospace;">').text(seqStr))
    $row.append($('<span class="sia-account text-muted" style="margin-right:6px; font-family:monospace;">').text(accountStr))
    $row.append($('<span class="sia-context text-muted" style="margin-right:6px;">').text(isRoutine ? '{{routine}}' : '{{non-routine}}'))
    $row.append($('<span class="sia-status label ' + badgeClass + '" style="margin-right:6px;">').text(badgeText))
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

  function addRow(label, value) {
    var $tr = $('<tr>')
    $tr.append($('<td>').text(label))
    var $td = $('<td>')
    if (value !== null && value !== undefined && value !== '') {
      $td.append($('<code>').text(String(value)))
    } else {
      $td.append($('<em class="text-muted">').text('—'))
    }
    $tbody.append($tr.append($td))
  }

  addRow('ID Token', decoded.id_token)
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
