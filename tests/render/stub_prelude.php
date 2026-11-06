<?php
// Rendering harness (story 17.14): minimal Jeedom stubs so desktop/php/siaDC09.php can run
// outside Jeedom and print its real HTML. Used through `php -d auto_prepend_file=...`.
function isConnect($right = null) { return true; }
function sendVarToJS($key, $value) { echo '<script>var ' . $key . ' = ' . json_encode($value) . ';</script>'; }
function include_file($folder, $name, $type, $plugin = '') { /* assets are added by render_wizard.py */ }
function __($text, $file = null) { return $text; }
class plugin {
    public static function byId($id) { return new self(); }
    public function getId() { return 'siaDC09'; }
}
class siaDC09 {
    public static function getCsrProfiles(): array {
        $data = json_decode(file_get_contents(__DIR__ . '/../../core/config/csr_presets.json'), true);
        return $data['profiles'];
    }
    public static function ensureAutoEquipment() {}
}
class eqLogic {
    public static function byType($type) { return []; }
}
class jeeObject {
    public static function buildTree($a = null, $b = false) { return []; }
}
class scenario {
    public static function all() { return []; }
}
