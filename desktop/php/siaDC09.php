<?php
if (!isConnect('admin')) {
	throw new Exception('{{401 - Accès non autorisé}}');
}
$plugin = plugin::byId('siaDC09');
sendVarToJS('eqType', $plugin->getId());
sendVarToJS('siaDC09_csrProfiles', siaDC09::getCsrProfiles());
// First access bootstraps the auto-equipment — the wizard runs with the daemon
// stopped, so deamon_start() never gets the chance to create it (Story 12.1 AC8).
siaDC09::ensureAutoEquipment();
$eqLogics = eqLogic::byType($plugin->getId());

// Step 4 offers the internal action `scenario`, whose target is picked from a plain <select>
// rendered here — no AJAX endpoint needed, the wizard page is already admin-only.
$scenarios = scenario::all();
?>

<div class="row row-overflow">
	<!-- Page d'accueil du plugin -->
	<div class="col-xs-12 eqLogicThumbnailDisplay">
		<div class="row">
			<div class="col-sm-10">
				<legend><i class="fas fa-cog"></i> {{Gestion}}</legend>
				<div class="eqLogicThumbnailContainer">
					<div class="cursor eqLogicAction logoPrimary" data-action="add">
						<i class="fas fa-plus-circle"></i>
						<br>
						<span>{{Ajouter}}</span>
					</div>
					<div class="cursor eqLogicAction logoSecondary" data-action="gotoPluginConf">
						<i class="fas fa-wrench"></i>
						<br>
						<span>{{Configuration}}</span>
					</div>
				</div>
			</div>
		</div>
		<legend><i class="fas fa-table"></i> {{Mes équipements SIA DC-09}}</legend>
		<?php
		if (count($eqLogics) == 0) {
			echo '<br><div class="text-center" style="font-size:1.2em;font-weight:bold;">{{Aucun équipement trouvé, cliquer sur "Ajouter" pour commencer}}</div>';
		} else {
			echo '<div class="input-group" style="margin:5px;">';
			echo '<input class="form-control roundedLeft" placeholder="{{Rechercher}}" id="in_searchEqlogic">';
			echo '<div class="input-group-btn">';
			echo '<a id="bt_resetSearch" class="btn" style="width:30px"><i class="fas fa-times"></i></a>';
			echo '<a class="btn roundedRight hidden" id="bt_pluginDisplayAsTable" data-coreSupport="1" data-state="0"><i class="fas fa-grip-lines"></i></a>';
			echo '</div>';
			echo '</div>';
			echo '<div class="eqLogicThumbnailContainer">';
			foreach ($eqLogics as $eqLogic) {
				$opacity = ($eqLogic->getIsEnable()) ? '' : 'disableCard';
				echo '<div class="eqLogicDisplayCard cursor ' . $opacity . '" data-eqLogic_id="' . $eqLogic->getId() . '">';
				echo '<img src="' . $eqLogic->getImage() . '"/>';
				echo '<br>';
				echo '<span class="name">' . $eqLogic->getHumanName(true, true) . '</span>';
				echo '</div>';
			}
			echo '</div>';
		}
		?>
	</div> <!-- /.eqLogicThumbnailDisplay -->

	<!-- Page de l'équipement -->
	<div class="col-xs-12 eqLogic" style="display: none;">
		<!-- Barre de gestion -->
		<div class="input-group pull-right" style="display:inline-flex;">
			<span class="input-group-btn">
				<a class="btn btn-sm btn-default eqLogicAction roundedLeft" data-action="configure"><i class="fas fa-cogs"></i><span class="hidden-xs"> {{Configuration avancée}}</span>
				</a><a class="btn btn-sm btn-default eqLogicAction" data-action="copy"><i class="fas fa-copy"></i><span class="hidden-xs"> {{Dupliquer}}</span>
				</a><a class="btn btn-sm btn-success eqLogicAction" data-action="save"><i class="fas fa-check-circle"></i> {{Sauvegarder}}
				</a><a class="btn btn-sm btn-danger eqLogicAction roundedRight" data-action="remove"><i class="fas fa-minus-circle"></i> {{Supprimer}}
				</a>
			</span>
		</div>
		<!-- Onglets -->
		<ul class="nav nav-tabs" role="tablist">
			<li role="presentation"><a href="#" class="eqLogicAction" aria-controls="home" role="tab" data-toggle="tab" data-action="returnToThumbnailDisplay"><i class="fas fa-arrow-circle-left"></i></a></li>
			<li role="presentation" class="active"><a href="#eqlogictab" aria-controls="home" role="tab" data-toggle="tab"><i class="fas fa-tachometer-alt"></i> {{Equipement}}</a></li>
			<li role="presentation"><a href="#commandtab" aria-controls="home" role="tab" data-toggle="tab"><i class="fas fa-list"></i> {{Commandes}}</a></li>
			<li role="presentation" id="siaDC09_diagnosticTabLi" style="display:none;"><a href="#diagnosticTab" aria-controls="diagnostic" role="tab" data-toggle="tab"><i class="fas fa-stethoscope"></i> {{Diagnostic}}</a></li>
		</ul>
		<div class="tab-content">
			<!-- Onglet Equipement -->
			<div role="tabpanel" class="tab-pane active" id="eqlogictab">
				<form class="form-horizontal">
					<fieldset>
						<!-- Paramètres généraux -->
						<div class="col-lg-6">
							<legend><i class="fas fa-wrench"></i> {{Paramètres généraux}}</legend>
							<div class="form-group">
								<label class="col-sm-4 control-label">{{Nom de l'équipement}}</label>
								<div class="col-sm-6">
									<input type="text" class="eqLogicAttr form-control" data-l1key="id" style="display:none;">
									<input type="text" class="eqLogicAttr form-control" data-l1key="name" placeholder="{{Nom de l'équipement}}">
								</div>
							</div>
							<div class="form-group">
								<label class="col-sm-4 control-label">{{Objet parent}}</label>
								<div class="col-sm-6">
									<select class="eqLogicAttr form-control" data-l1key="object_id">
										<option value="">{{Aucun}}</option>
										<?php
										foreach ((jeeObject::buildTree(null, false)) as $object) {
											echo '<option value="' . $object->getId() . '">' . str_repeat('&nbsp;&nbsp;', $object->getConfiguration('parentNumber')) . $object->getName() . '</option>';
										}
										?>
									</select>
								</div>
							</div>
							<div class="form-group">
								<label class="col-sm-4 control-label">{{Options}}</label>
								<div class="col-sm-6">
									<label class="checkbox-inline"><input type="checkbox" class="eqLogicAttr" data-l1key="isEnable" checked>{{Activer}}</label>
									<label class="checkbox-inline"><input type="checkbox" class="eqLogicAttr" data-l1key="isVisible" checked>{{Visible}}</label>
								</div>
							</div>
							<div class="form-group">
								<div class="col-sm-offset-4 col-sm-6">
									<a class="btn btn-warning btn-sm" id="bt_restartWizard"><i class="fas fa-redo"></i> {{Relancer l'assistant}}</a>
								</div>
							</div>
						</div>

						<!-- Wizard / Config area -->
						<div class="col-lg-6">
							<!-- Hidden wizard step field -->
							<input type="hidden" class="eqLogicAttr" data-l1key="configuration" data-l2key="sia_wizard_step">

							<!-- WIZARD MODE -->
							<div id="siaDC09-wizard" style="display:none;">
								<!-- Step 1: CSR connection parameters -->
								<div id="siaDC09-step1" class="siaDC09-step" style="display:none;">
									<legend><i class="fas fa-satellite-dish"></i> {{Étape 1 — Centrale de télésurveillance}}</legend>

									<!-- Profile first: it presets the periodic-frame options (ADR-22) -->
									<div class="form-group">
										<label class="col-sm-4 control-label">{{Profil de la centrale}}</label>
										<div class="col-sm-6">
											<select class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="csr_profile" id="siaDC09-csr-profile">
												<?php
												foreach (siaDC09::getCsrProfiles() as $profileId => $profile) {
													echo '<option value="' . htmlspecialchars((string) $profileId) . '">' . htmlspecialchars((string) ($profile['label'] ?? $profileId)) . '</option>';
												}
												?>
												<option value="">{{Personnalisé}}</option>
											</select>
											<span class="help-block">{{Choisissez d'abord le profil de votre centrale : il règle automatiquement les options avancées.}}</span>
										</div>
									</div>

									<!-- CSR fields -->
									<div class="form-group">
										<label class="col-sm-4 control-label">{{Adresse IP}}</label>
										<div class="col-sm-6">
											<input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="csr_ip" placeholder="192.168.x.x">
										</div>
									</div>
									<div class="form-group">
										<label class="col-sm-4 control-label">{{Port}}</label>
										<div class="col-sm-6">
											<input type="number" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="csr_port" placeholder="5000">
										</div>
									</div>
									<div class="form-group">
										<label class="col-sm-4 control-label">{{Transport}}</label>
										<div class="col-sm-6">
											<select class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="transport">
												<option value="udp">UDP</option>
												<option value="tcp">TCP</option>
											</select>
										</div>
									</div>
									<div class="form-group">
										<label class="col-sm-4 control-label">{{Numéro de compte}}</label>
										<div class="col-sm-6">
											<input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="account_number" placeholder="ex: 001234">
										</div>
									</div>
									<div class="form-group">
										<label class="col-sm-4 control-label">{{Chiffrement activé}}</label>
										<div class="col-sm-6">
											<input type="checkbox" class="eqLogicAttr" data-l1key="configuration" data-l2key="encryption_enabled">
										</div>
									</div>
									<div class="form-group">
										<label class="col-sm-4 control-label">{{Clé AES}}</label>
										<div class="col-sm-6">
											<input type="password" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="encryption_key" placeholder="32, 48 ou 64 caractères hex">
										</div>
									</div>
									<div class="form-group">
										<label class="col-sm-4 control-label">{{Tentatives de reconnexion}}</label>
										<div class="col-sm-6">
											<input type="number" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="retry_count" placeholder="6">
										</div>
									</div>
									<div class="form-group">
										<label class="col-sm-4 control-label">{{Délai de reconnexion (s)}}</label>
										<div class="col-sm-6">
											<input type="number" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="reconnect_delay" placeholder="30">
										</div>
									</div>

									<!-- Options avancées (ADR-22) -->
									<div class="form-group">
										<div class="col-sm-offset-4 col-sm-6">
											<a class="btn btn-default btn-sm" id="bt_siaDC09_toggleAdvanced"><i class="fas fa-cog"></i> {{Options avancées}}</a>
										</div>
									</div>
									<div id="siaDC09-advanced" style="display:none;">
										<div class="form-group">
											<label class="col-sm-4 control-label">{{Trame de supervision}}</label>
											<div class="col-sm-6">
												<select class="eqLogicAttr form-control siaDC09-profile-field" data-l1key="configuration" data-l2key="supervision_format">
													<option value="none">{{Aucune}}</option>
													<option value="sia-dcs">SIA-DCS</option>
													<option value="null">NULL</option>
												</select>
												<div id="siaDC09-null-warning" class="alert alert-warning" style="display:none; margin-top:5px;">{{Le format NULL : certains récepteurs le rejettent.}}</div>
											</div>
										</div>
										<div class="form-group">
											<label class="col-sm-4 control-label">{{Intervalle supervision (s)}}</label>
											<div class="col-sm-6">
												<input type="number" class="eqLogicAttr form-control siaDC09-profile-field" data-l1key="configuration" data-l2key="supervision_interval" placeholder="60">
											</div>
										</div>
										<div class="form-group">
											<label class="col-sm-4 control-label">{{Test cyclique (RP)}}</label>
											<div class="col-sm-6">
												<input type="checkbox" class="eqLogicAttr siaDC09-profile-field" data-l1key="configuration" data-l2key="rp_enabled">
											</div>
										</div>
										<div class="form-group">
											<label class="col-sm-4 control-label">{{Intervalle RP (s)}}</label>
											<div class="col-sm-6">
												<input type="number" class="eqLogicAttr form-control siaDC09-profile-field" data-l1key="configuration" data-l2key="rp_interval" placeholder="60" min="60" max="86400">
											</div>
										</div>
									</div>

									<!-- Validation errors -->
									<div id="siaDC09-step1-errors" class="alert alert-danger" style="display:none;"></div>

									<!-- Navigation -->
									<div class="form-group">
										<div class="col-sm-offset-4 col-sm-6">
											<a class="btn btn-success" id="bt_step1Next"><i class="fas fa-arrow-right"></i> {{Suivant}}</a>
										</div>
									</div>
								</div><!-- /#siaDC09-step1 -->

								<!-- Step 2: Connection Test -->
								<div id="siaDC09-step2" class="siaDC09-step" style="display:none;">
									<legend><i class="fas fa-plug"></i> {{Étape 2 — Test de connexion}}</legend>

									<!-- CSR summary -->
									<div id="siaDC09-step2-summary" class="well well-sm" style="margin-bottom:15px;"></div>

									<!-- Spinner -->
									<div id="siaDC09-step2-spinner" style="display:none;text-align:center;margin:20px 0;">
										<i class="fas fa-spinner fa-spin fa-2x"></i>
										<p>{{Test en cours...}}</p>
									</div>

									<!-- Result area -->
									<div id="siaDC09-step2-result" style="display:none;margin:15px 0;"></div>

									<!-- Buttons -->
									<div class="form-group">
										<div class="col-sm-12" style="text-align:right;">
											<a class="btn btn-default" id="bt_step2Retest"><i class="fas fa-redo"></i> {{Relancer le test}}</a>
											<a class="btn btn-warning" id="bt_step2Skip"><i class="fas fa-forward"></i> {{Ignorer}}</a>
											<a class="btn btn-success" id="bt_step2Next" disabled><i class="fas fa-arrow-right"></i> {{Suivant}}</a>
										</div>
									</div>
								</div><!-- /#siaDC09-step2 -->

								<!-- Step 3: Zone Mapping -->
								<div id="siaDC09-step3" class="siaDC09-step" style="display:none;">
									<legend><i class="fas fa-map-marker-alt"></i> {{Étape 3 — Zones}}</legend>
									<div id="siaDC09-step3-warning" class="alert alert-warning" style="display:none;">
										<i class="fas fa-exclamation-triangle"></i> {{Le test de connexion a été ignoré. La connexion à la centrale n'a pas été vérifiée.}}
									</div>
									<div id="siaDC09-step3-nozone" class="alert alert-warning" style="display:none;">
										<i class="fas fa-exclamation-triangle"></i> {{Aucune zone détectée — configurez d'abord votre plugin alarme.}}
									</div>
									<div id="siaDC09-step3-nocamera" class="alert alert-warning" style="display:none;">
										<i class="fas fa-exclamation-triangle"></i> {{Aucune caméra Frigate détectée — installez et configurez le plugin Frigate NVR pour rattacher un aperçu aux alarmes.}}
									</div>
									<div class="form-group">
										<label class="col-sm-4 control-label">{{URL media Frigate}}</label>
										<div class="col-sm-6">
											<input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="frigate_media_url_template" placeholder="https://<user>:<pass>@host/ ou https://host/?accesstoken=<token>">
											<p class="help-block">{{Optionnel — voir}} <a href="https://hlehoux2021.github.io/siadc09/fr_FR/#photos-et-vidéos-frigate-optionnel" target="_blank" rel="noopener">{{la documentation Frigate}}</a>.</p>
										</div>
									</div>
									<div class="table-responsive">
										<table id="siaDC09-zone-table" class="table table-bordered table-condensed">
											<thead>
												<tr>
													<th style="width:60px;">{{N°}}</th>
													<th>{{Zone d'alarme}}</th>
													<th>{{Caméra Frigate}} <small class="text-muted">{{(optionnel)}}</small></th>
												</tr>
											</thead>
											<tbody id="siaDC09-zone-tbody">
											</tbody>
										</table>
									</div>
									<p class="text-muted">
										<i class="fas fa-info-circle"></i> {{Prefetch événement Frigate : à câbler aux actions immédiates de déclenchement (globales, recommandé), Titre =}} <code>#zone#</code> — <a href="https://hlehoux2021.github.io/siadc09/fr_FR/#câbler-le-plugin-alarme" target="_blank" rel="noopener">{{voir la documentation de câblage}}</a>.
									</p>
									<div class="form-group">
										<label class="col-sm-4 control-label">{{Numéro utilisateur SIA}}</label>
										<div class="col-sm-6">
											<input type="number" min="1" max="999" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="sia_user_number" placeholder="1">
											<p class="help-block">{{Numéro déclaré à la centrale pour identifier l'utilisateur Jeedom lors d'une annulation/désarmement.}}</p>
										</div>
									</div>
									<p class="text-muted">
										<i class="fas fa-info-circle"></i> {{Trois commandes à câbler dans le plugin Alarme —}} <a href="https://hlehoux2021.github.io/siadc09/fr_FR/#câbler-le-plugin-alarme" target="_blank" rel="noopener">{{voir la documentation de câblage}}</a>.
									</p>
									<div class="form-group" style="margin-top:15px;">
										<div class="col-sm-12" style="text-align:right;">
											<a class="btn btn-success" id="bt_step3Next"><i class="fas fa-arrow-right"></i> {{Suivant}}</a>
										</div>
									</div>
								</div><!-- /#siaDC09-step3 -->

								<!-- Step 4: Critical Notifications -->
								<div id="siaDC09-step4" class="siaDC09-step" style="display:none;">
									<legend><i class="fas fa-bell"></i> {{Étape 4 — Alertes critiques}}</legend>
									<p class="text-muted">
										{{En cas de problème grave (supervision perdue, alarme non transmise), le plugin doit prévenir quelqu'un.}}
									</p>
									<div class="form-group">
										<label class="col-sm-4 control-label">{{Type de notification}}</label>
										<div class="col-sm-7">
											<select class="eqLogicAttr form-control" id="siaDC09_notifyKind"
													data-l1key="configuration" data-l2key="sia_notify_kind">
												<option value="cmd">{{Commande d'un équipement (SMS, Telegram, push…)}}</option>
												<option value="internal">{{Action interne Jeedom}}</option>
											</select>
										</div>
									</div>
									<div class="form-group siaDC09-notify-cmd">
										<label class="col-sm-4 control-label">{{Commande de notification}}</label>
										<div class="col-sm-7">
											<div class="input-group">
												<input type="text"
													   class="eqLogicAttr form-control"
													   data-l1key="configuration"
													   data-l2key="sia_notify_cmd_human"
													   readonly
													   placeholder="{{Sélectionnez une commande de notification}}">
												<span class="input-group-btn">
													<a class="btn btn-default cursor" id="siaDC09_searchNotifyCmd">
														<i class="fas fa-list-alt"></i>
													</a>
												</span>
											</div>
											<input type="hidden"
												   class="eqLogicAttr"
												   data-l1key="configuration"
												   data-l2key="sia_notify_cmd_id">
											<span class="help-block">
												{{La liste ne propose que les commandes de type « action » et de sous-type « message », c'est-à-dire celles qui acceptent un titre et un texte : SMS, Telegram, notification mobile, e-mail. Les interrupteurs, curseurs et informations n'y apparaissent pas.}}
											</span>
										</div>
									</div>
									<div class="form-group siaDC09-notify-internal">
										<label class="col-sm-4 control-label">{{Action interne}}</label>
										<div class="col-sm-7">
											<select class="eqLogicAttr form-control" id="siaDC09_notifyInternal"
													data-l1key="configuration" data-l2key="sia_notify_internal">
												<option value="">{{Choisissez une action}}</option>
												<option value="message">{{message — ajouter au centre de messages Jeedom}}</option>
												<option value="scenario">{{scenario — lancer un scénario}}</option>
											</select>
										</div>
									</div>
									<div class="form-group siaDC09-notify-scenario">
										<label class="col-sm-4 control-label">{{Scénario à lancer}}</label>
										<div class="col-sm-7">
											<select class="eqLogicAttr form-control" id="siaDC09_notifyScenario"
													data-l1key="configuration" data-l2key="sia_notify_scenario_id">
												<option value="">{{Choisissez un scénario}}</option>
												<?php foreach ($scenarios as $notifyScenario): ?>
												<option value="<?= (int) $notifyScenario->getId() ?>"><?= htmlspecialchars($notifyScenario->getHumanName()) ?></option>
												<?php endforeach; ?>
											</select>
											<span class="help-block">
												{{Le scénario est lancé avec « siaDC09 » comme déclencheur ; le texte de l'alerte est inscrit dans son historique.}}
											</span>
										</div>
									</div>
									<div id="siaDC09-step4-error" class="alert alert-danger" style="display:none;">
										<i class="fas fa-exclamation-circle"></i> {{Veuillez sélectionner une commande. Vous pouvez toujours utiliser la messagerie Jeedom.}}
									</div>
									<div id="siaDC09-step4-error-internal" class="alert alert-danger" style="display:none;">
										<i class="fas fa-exclamation-circle"></i> {{Veuillez choisir l'action interne à exécuter.}}
									</div>
									<div id="siaDC09-step4-error-scenario" class="alert alert-danger" style="display:none;">
										<i class="fas fa-exclamation-circle"></i> {{Veuillez choisir le scénario à lancer.}}
									</div>
									<div class="form-group" style="margin-top:15px;">
										<div class="col-sm-offset-4 col-sm-7">
											<a class="btn btn-success" id="bt_step4Finish"><i class="fas fa-check"></i> {{Terminer}}</a>
										</div>
									</div>
								</div><!-- /#siaDC09-step4 -->
							</div><!-- /#siaDC09-wizard -->

							<!-- CONFIG MODE (step == 4) -->
							<div id="siaDC09-config-summary" style="display:none;">
								<legend><i class="fas fa-info-circle"></i> {{Configuration active}}</legend>
								<div class="well well-sm" style="margin-top:10px;">
									<strong>{{Connexion}}</strong>
									<div id="siaDC09-summary-connection" style="margin:8px 0 12px 10px;"></div>
									<strong>{{Zones mappées}}</strong>
									<div id="siaDC09-summary-zones" style="margin:8px 0 12px 10px;"></div>
									<strong>{{Notification critique}}</strong>
									<div id="siaDC09-summary-notify" style="margin:8px 0 0 10px;"></div>
								</div>
							</div>
						</div>
					</fieldset>
				</form>
			</div><!-- /.tabpanel #eqlogictab -->

			<!-- Onglet Commandes -->
			<div role="tabpanel" class="tab-pane" id="commandtab">
				<div class="table-responsive">
					<table id="table_cmd" class="table table-bordered table-condensed">
						<thead>
							<tr>
								<th class="hidden-xs" style="min-width:50px;width:70px;">ID</th>
								<th style="min-width:200px;width:350px;">{{Nom}}</th>
								<th>{{Type}}</th>
								<th style="min-width:260px;">{{Options}}</th>
								<th>{{Etat}}</th>
								<th style="min-width:80px;width:200px;">{{Actions}}</th>
							</tr>
						</thead>
						<tbody>
						</tbody>
					</table>
				</div>
			</div><!-- /.tabpanel #commandtab -->

			<!-- Onglet Diagnostic -->
			<div role="tabpanel" class="tab-pane" id="diagnosticTab">
				<!-- Status badge -->
				<div class="panel panel-default" id="siaDC09_statusPanel">
					<div class="panel-body" style="display:flex;flex-wrap:wrap;gap:30px;">
						<!-- SM1 card (same layout as the dashboard widget) -->
						<div style="display:flex;align-items:center;gap:10px;min-width:220px;">
							<span id="siaDC09_badge" class="text-warning" style="flex:none;display:inline-flex;align-items:center;justify-content:center;width:2.2em;height:2.2em;border:2px solid currentColor;border-radius:50%;">
								<i id="siaDC09_badgeIcon" class="fas fa-question-circle"></i>
							</span>
							<span style="min-width:0;line-height:1.25;">
								<span id="siaDC09_badgeLabel" style="display:block;font-weight:bold;"></span>
								<span id="siaDC09_badgeSub" style="display:none;font-size:0.85em;opacity:0.7;"></span>
								<span id="siaDC09_badgeTime" style="display:block;font-size:0.85em;opacity:0.7;"></span>
							</span>
						</div>
						<!-- SM2 card: last event -->
						<div style="min-width:260px;">
							<div style="font-size:0.75em;font-weight:bold;opacity:0.6;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:3px;">{{Dernier événement}}</div>
							<div style="display:flex;gap:8px;word-break:break-word;">
								<span id="siaDC09_eventBar" class="text-muted" style="flex:none;width:4px;border-radius:2px;background:currentColor;opacity:0.85;"></span>
								<div style="min-width:0;flex:1;">
									<div id="siaDC09_eventHead" style="display:none;align-items:center;gap:10px;margin-bottom:4px;">
										<span id="siaDC09_eventTypeWrap" style="flex:none;display:inline-flex;align-items:center;justify-content:center;width:2.2em;height:2.2em;border:2px solid currentColor;border-radius:50%;">
											<i id="siaDC09_eventTypeIcon" class="fas"></i>
										</span>
										<span style="min-width:0;line-height:1.25;">
											<span id="siaDC09_eventTypeText" style="display:block;font-weight:bold;"></span>
											<span id="siaDC09_eventWhere" style="display:block;font-size:0.85em;opacity:0.7;"></span>
										</span>
									</div>
									<div>
										<i id="siaDC09_eventStatusIcon" class="fas" style="display:none;font-size:1.25em;vertical-align:middle;margin-right:2px;"></i>
										<span id="siaDC09_eventBadgeLabel" class="text-muted" style="font-weight:bold;"></span>
										<span id="siaDC09_eventTime" style="opacity:0.7;"></span>
									</div>
								</div>
							</div>
						</div>
					</div>
				</div>
				<!-- Error panel -->
				<div class="panel panel-default" id="siaDC09_errorsPanel">
					<div class="panel-heading">
						{{Dernières erreurs}}
						<button class="btn btn-xs btn-danger pull-right" id="siaDC09_errorsClear" style="margin-left:5px;">{{Vider}}</button>
						<button class="btn btn-xs btn-default pull-right" id="siaDC09_errorsRefresh">{{Actualiser}}</button>
					</div>
					<div class="panel-body" id="siaDC09_errorsList">
						<em class="text-muted">{{Aucune erreur enregistrée}}</em>
					</div>
				</div>
				<!-- Protocol inspector (placeholder for story 9-2) -->
				<div class="panel panel-default" id="siaDC09_inspectorPanel">
					<div class="panel-heading">
						{{Inspecteur de protocole}}
						<button class="btn btn-xs btn-danger pull-right" id="siaDC09_inspectorClear" style="margin-left:5px;">{{Vider}}</button>
						<button class="btn btn-xs btn-default pull-right" id="siaDC09_inspectorRefresh">{{Actualiser}}</button>
					</div>
					<div class="panel-body" id="siaDC09_inspectorList">
						<em class="text-muted">{{Aucun échange SIA enregistré}}</em>
					</div>
				</div>
			</div><!-- /.tabpanel #diagnosticTab -->
		</div><!-- /.tab-content -->
	</div><!-- /.eqLogic -->
</div><!-- /.row row-overflow -->

<?php include_file('desktop', 'siaDC09', 'js', 'siaDC09'); ?>
<?php include_file('core', 'plugin.template', 'js'); ?>
