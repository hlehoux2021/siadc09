#!/usr/bin/env python3
"""Render the wizard screens A-D of the 17.14 mockup into standalone HTML files.

The real desktop/php/siaDC09.php runs under stub_prelude.php; the page is wrapped with the REAL
Jeedom CSS (helpers/jeedom/core, read-only), the plugin CSS and the real desktop/js/siaDC09.js,
and a small driver puts the page in the state of each mockup screen.

Usage: python3 tests/render/render_wizard.py [--theme Light|Dark] [--out DIR] [--screenshot BROWSER]
Open the .html files in any browser. With --screenshot (path of a Chrome/Firefox binary) a PNG
is also taken per screen when the browser can run (it cannot inside the Claude sandbox).
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JEEDOM = ROOT.parents[2] / "helpers" / "jeedom" / "core"  # .claude/worktrees/<x> -> project root
I18N = re.compile(r"\{\{(.*?)\}\}", re.S)

SCREENS = {
    "A": "step 1, FoxStream, Frigate address missing (error shown)",
    "B": "step 2, test OK, Options avancées unfolded, profile locked",
    "C": "step 2, test refused (DUH), Options avancées folded",
    "D": "step 3, zones and alertes",
}

DRIVER = """
$.ajax = function() { return { }; }
window.jeedom = { eqLogic: { save: function() {}, byId: function() {} }, plugin: { getDeamonInfo: function(o) { o.success({state: 'nok'}) }, deamonStop: function() {} }, cmd: {} }
window.jeeDialog = { confirm: function() {} }
window.jeeFrontEnd = {}
$.fn.showAlert = function() {}
$.fn.getValues = function() { return [{ id: '1' }] }
$('.eqLogicThumbnailDisplay').hide(); $('.eqLogic').show(); $('#siaDC09-wizard').show()
var screen = '%(screen)s'
var cfg = { csr_profile: 'foxstream', csr_ip: '194.51.213.114', csr_port: '5394', transport: 'tcp',
  account_number: '4596', media_enabled: 1, frigate_media_url_template: screen === 'A' ? '' : 'https://frigate.maison.fr',
  supervision_format: 'sia-dcs', supervision_interval: 30, rp_enabled: 1, rp_interval: 120, sia_wizard_step: 1 }
$('.eqLogicAttr').each(function() {
  var k = $(this).attr('data-l2key'); if (!k || cfg[k] === undefined) return
  if ($(this).is(':checkbox')) $(this).prop('checked', !!cfg[k]); else $(this).val(cfg[k])
})
printEqLogic({ configuration: cfg })
if (screen === 'A') { siaDC09_showStep(1); siaDC09_validateStep1() }
if (screen === 'B' || screen === 'C') {
  siaDC09_showStep(2)
  var $r = $('#siaDC09-step2-sia-body').empty()
  _siaDC09_hasTested = true
  if (screen === 'B') {
    $r.append('<div class="alert alert-success siaDC09-test-success"><i class="fas fa-check-circle"></i> <span>Connexion établie - ACK reçu</span></div>')
    _siaDC09_tests.sia = 'ok'
    siaDC09_setAdvancedOpen(true)
  } else {
    $r.append(siaDC09_renderStep2Failure({ outcome: 'duh', sent: { type: 'trame de supervision SIA-DCS', account: '4596', transport: 'TCP' } }))
    _siaDC09_tests.sia = 'fail'
  }
  siaDC09_refreshStep2Buttons()
}
if (screen === 'D') {
  siaDC09_showStep = function() {}
  $('.siaDC09-step').hide(); $('#siaDC09-step3').show()
  $('#siaDC09-stepper li').removeClass('active'); $('#siaDC09-stepper li[data-step="3"]').addClass('active')
  siaDC09_loadZoneTable(['Salon', 'Garage'], [], [])
  siaDC09_toggleNotifyTarget()
}
"""


def render_page(php_html: str, js: str, css: str, theme: str, screen: str) -> str:
    strip = lambda s: I18N.sub(r"\1", s)
    core = JEEDOM
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>wizard {screen} ({theme})</title>
<link rel="stylesheet" href="file://{core}/desktop/css/bootstrap.css">
<link rel="stylesheet" href="file://{core}/3rdparty/font-awesome5/css/all.min.css">
<link rel="stylesheet" href="file://{core}/core/themes/core2019_{theme}/desktop/colors.css">
<link rel="stylesheet" href="file://{core}/desktop/css/desktop.main.css">
<link rel="stylesheet" href="file://{core}/core/themes/core2019_{theme}/desktop/core2019_{theme}.css">
<style>{css}</style></head>
<body><div id="div_pageContainer" class="container-fluid" style="padding-top:20px;"><div id="div_alert"></div>
{strip(php_html)}
</div>
<script src="file://{core}/3rdparty/jquery/jquery.min.js"></script>
<script>$.fn.sortable = function() {{ return this }}</script>
<script>{strip(js)}</script>
<script>{DRIVER % {"screen": screen}}</script></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default="Light", choices=["Light", "Dark"])
    ap.add_argument("--out", default=str(ROOT / ".cleanup" / "screens"))
    ap.add_argument("--screenshot", default="")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    php = subprocess.run(
        ["php", "-d", f"auto_prepend_file={ROOT / 'tests/render/stub_prelude.php'}", str(ROOT / "desktop/php/siaDC09.php")],
        capture_output=True, text=True, check=True, cwd=ROOT).stdout
    js = (ROOT / "desktop/js/siaDC09.js").read_text(encoding="utf-8")
    css = (ROOT / "desktop/css/siaDC09.css").read_text(encoding="utf-8")
    for screen, label in SCREENS.items():
        page = out / f"wizard-{screen}-{args.theme}.html"
        page.write_text(render_page(php, js, css, args.theme, screen), encoding="utf-8")
        print(f"{page}  ({label})")
        if args.screenshot:
            png = page.with_suffix(".png")
            subprocess.run([args.screenshot, "--headless", "--window-size=1400,1400", f"--screenshot={png}", f"file://{page}"], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
