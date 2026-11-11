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
									<a class="btn btn-default btn-sm" id="bt_unlinkAlarm" style="display:none;"><i class="fas fa-unlink"></i> {{Délier du plugin Alarme}}</a>
								</div>
							</div>
						</div>

						<!-- Wizard / Config area -->
						<div class="col-lg-6">
							<!-- Hidden wizard step field -->
							<input type="hidden" class="eqLogicAttr" data-l1key="configuration" data-l2key="sia_wizard_step">

							<!-- WIZARD MODE (story 17.14: three steps, layout from the Excalidraw mockup) -->
							<div id="siaDC09-wizard" style="display:none;">
								<!-- Stepper: read-only, the active tab follows siaDC09_showStep() -->
								<ul class="siaDC09-stepper" id="siaDC09-stepper" aria-label="{{Étapes de l'assistant}}">
									<li data-step="1" class="active" aria-current="step">1&nbsp;&nbsp;{{Centrale}}</li>
									<li data-step="2">2&nbsp;&nbsp;{{Test}}</li>
									<li data-step="3">3&nbsp;&nbsp;{{Zones et alertes}}</li>
								</ul>

								<!-- Step 1: the center and the photo/video verification -->
								<div id="siaDC09-step1" class="siaDC09-step" style="display:none;">
									<div class="siaDC09-zone" id="siaDC09-center-card">
										<h4 class="siaDC09-zone-title">{{Votre centrale de télésurveillance}}</h4>

										<!-- Profile first: it presets the periodic-frame options (ADR-22) -->
										<div class="siaDC09-row">
											<div class="siaDC09-field siaDC09-w-input">
												<label class="siaDC09-label" for="siaDC09-csr-profile">{{Profil de la centrale}}</label>
												<select class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="csr_profile" id="siaDC09-csr-profile">
													<?php
													foreach (siaDC09::getCsrProfiles() as $profileId => $profile) {
														echo '<option value="' . htmlspecialchars((string) $profileId) . '">' . htmlspecialchars((string) ($profile['label'] ?? $profileId)) . '</option>';
													}
													?>
													<option value="">{{Personnalisé}}</option>
												</select>
											</div>
											<p class="siaDC09-help siaDC09-help-side">{{Le profil règle pour vous les options de votre centrale. « Personnalisé » = mode expert : vous réglez tout.}}</p>
										</div>

										<div class="siaDC09-row">
											<div class="siaDC09-field siaDC09-w-wide">
												<label class="siaDC09-label">{{Adresse IP de la centrale}}</label>
												<input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="csr_ip" placeholder="192.168.x.x">
											</div>
											<div class="siaDC09-field siaDC09-w-narrow">
												<label class="siaDC09-label">{{Port}}</label>
												<input type="number" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="csr_port" placeholder="5000">
											</div>
											<div class="siaDC09-field siaDC09-w-mid">
												<label class="siaDC09-label">{{Transport}}</label>
												<select class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="transport">
													<option value="udp">UDP</option>
													<option value="tcp">TCP</option>
												</select>
											</div>
										</div>

										<div class="siaDC09-row">
											<div class="siaDC09-field siaDC09-w-wide">
												<label class="siaDC09-label">{{Numéro de compte}}</label>
												<input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="account_number" placeholder="ex: 001234">
											</div>
											<div class="siaDC09-field siaDC09-w-wide">
												<label class="siaDC09-check-line"><input type="checkbox" class="eqLogicAttr" data-l1key="configuration" data-l2key="encryption_enabled">{{Chiffrer les échanges (clé AES)}}</label>
											</div>
										</div>
										<div class="siaDC09-row" id="siaDC09-aes-row" style="display:none;">
											<div class="siaDC09-field siaDC09-w-input">
												<label class="siaDC09-label">{{Clé AES}}</label>
												<input type="password" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="encryption_key" placeholder="32, 48 ou 64 caractères hex">
											</div>
										</div>
									</div>

									<!-- Levée de doute photo / vidéo (stories 17.10, 18.4) : média et transport au choix de l'utilisateur ; photo/vidéo suivent le profil -->
									<div class="siaDC09-zone" id="siaDC09-media-card">
										<h4 class="siaDC09-zone-title">{{Levée de doute photo / vidéo}}</h4>
										<label class="siaDC09-check-line">
											<input type="checkbox" class="eqLogicAttr siaDC09-media-field" id="siaDC09-media-enabled" data-l1key="configuration" data-l2key="media_enabled" aria-describedby="siaDC09-media-help">{{Joindre une photo ou une vidéo à l'alarme (levée de doute)}}
										</label>
										<p class="siaDC09-help" id="siaDC09-media-help">{{Le télésurveilleur peut ainsi voir ce qui a déclenché l'alarme.}}</p>
										<p class="siaDC09-help" id="siaDC09-media-nomedia" style="display:none;">{{Cette centrale ne reçoit ni photo ni vidéo.}}</p>
										<div id="siaDC09-media-body" style="display:none;">
											<div class="siaDC09-subzone" id="siaDC09-media-profile-group">
												<h5 class="siaDC09-zone-title">{{Contenu et mode d'envoi}}</h5>
											<div class="siaDC09-field siaDC09-w-full" id="siaDC09-media-what" style="margin-top:14px;">
												<span class="siaDC09-label">{{Que joindre ?}}</span>
												<label class="siaDC09-check-line"><input type="checkbox" class="eqLogicAttr siaDC09-media-field siaDC09-profile-field" data-l1key="configuration" data-l2key="media_snapshot_enabled">{{Photo}}</label>
												<label class="siaDC09-check-line"><input type="checkbox" class="eqLogicAttr siaDC09-media-field siaDC09-profile-field" data-l1key="configuration" data-l2key="media_clip_enabled">{{Vidéo}}</label>
											</div>
											<div class="siaDC09-field siaDC09-w-full" id="siaDC09-media-transport-group" style="margin-top:14px;">
												<span class="siaDC09-label">{{Comment la centrale reçoit-elle la photo ou la vidéo ?}}</span>
												<!-- media_transport is the saved field ('url' | 'ftps'); the radios drive it (Jeedom does not save radios as eqLogicAttr) -->
												<input type="hidden" class="eqLogicAttr siaDC09-media-field" data-l1key="configuration" data-l2key="media_transport">
												<div class="radio"><label><input type="radio" class="siaDC09-transport-radio siaDC09-transport-field siaDC09-profile-field" name="siaDC09-media-transport" value="url"> {{Une adresse (URL) dans le message d'alarme}}</label>
													<p class="siaDC09-help">{{La centrale va chercher le média sur votre serveur Frigate.}}</p></div>
												<div class="radio"><label><input type="radio" class="siaDC09-transport-radio siaDC09-transport-field siaDC09-profile-field" name="siaDC09-media-transport" value="ftps"> {{Une copie déposée sur un serveur FTPS}}</label>
													<p class="siaDC09-help">{{Le plugin dépose le média sur votre serveur ; le message d'alarme ne contient pas d'adresse.}}</p></div>
											</div>
												<p class="siaDC09-help" id="siaDC09-media-lock-note" style="display:none;"><i class="fas fa-lock"></i> <span></span></p>
											</div><!-- /#siaDC09-media-profile-group -->
											<div class="siaDC09-subzone" id="siaDC09-media-url-group" style="display:none;">
												<h5 class="siaDC09-zone-title">{{Adresse pour la centrale}}</h5>
												<label class="siaDC09-label">{{Adresse de votre serveur Frigate *}}</label>
												<input type="text" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="frigate_media_url_template" placeholder="https://frigate.maison.fr">
												<p class="siaDC09-help">{{Exemple : https://frigate.maison.fr}} — <a href="https://hlehoux2021.github.io/siadc09/fr_FR/#photos-et-vidéos-frigate-optionnel" target="_blank" rel="noopener">{{la documentation Frigate}}</a>.</p>
											</div>
											<!-- Shown under FTPS (story 18.11): the settings are on step 2, in the advanced options -->
											<p class="siaDC09-help" id="siaDC09-media-ftps-note" style="display:none;margin-top:14px;">{{Les réglages du serveur FTPS se font à l'étape suivante, dans les options avancées.}}</p>
										</div>
									</div>

									<!-- Validation errors -->
									<div id="siaDC09-step1-errors" class="alert alert-danger siaDC09-banner-error" role="alert" style="display:none;"></div>

									<!-- Navigation -->
									<div class="siaDC09-actions">
										<a class="btn btn-success" id="bt_step1Next"><i class="fas fa-arrow-right"></i> {{Suivant}}</a>
									</div>
								</div><!-- /#siaDC09-step1 -->

								<!-- Step 2: connection test + advanced options -->
								<div id="siaDC09-step2" class="siaDC09-step" style="display:none;">
									<!-- CSR summary -->
									<div id="siaDC09-step2-summary" class="siaDC09-summary"></div>

									<!-- One result zone per test (story 18.12); nothing runs on arrival, the zones are filled by JS -->
									<div class="siaDC09-zone siaDC09-testzone" id="siaDC09-step2-sia">
										<h4 class="siaDC09-zone-title">{{Test de la centrale (SIA)}}</h4>
										<div class="siaDC09-testzone-body" id="siaDC09-step2-sia-body"></div>
									</div>
									<div class="siaDC09-zone siaDC09-testzone" id="siaDC09-step2-ftps" style="display:none;">
										<h4 class="siaDC09-zone-title">{{Test du serveur FTPS}}</h4>
										<p class="siaDC09-help">{{Ce test vérifie : la connexion, le certificat, l'identifiant (aucun fichier n'est écrit).}}</p>
										<div class="siaDC09-testzone-body" id="siaDC09-step2-ftps-body"></div>
									</div>

									<!-- Options avancées (ADR-22): dashed bar, content BELOW it -->
									<a class="siaDC09-advbar" id="bt_siaDC09_toggleAdvanced" role="button" tabindex="0" aria-expanded="false" aria-controls="siaDC09-advanced">
										<span class="siaDC09-advbar-title"><i class="fas fa-chevron-right" id="siaDC09-advbar-icon"></i><span id="siaDC09-advbar-title-text">{{Options avancées : contenu envoyé, supervision de la liaison}}</span></span>
										<span class="siaDC09-advbar-hint" id="siaDC09-advbar-hint">{{(cliquez pour afficher ; s'ouvre toute seule si une erreur s'y trouve)}}</span>
									</a>

									<div id="siaDC09-advanced" style="display:none;">
										<!-- One caption for the whole panel, only while a profile locks it -->
										<p class="siaDC09-lock-caption" id="siaDC09-lock-caption" style="display:none;"><i class="fas fa-lock"></i> <span></span> <a class="btn btn-default btn-xs" id="bt_siaDC09_goCustom">{{Passer en Personnalisé}}</a></p>

										<!-- Contenu envoyé avec l'alarme (stories 17.7, 17.10, 17.11) -->
										<div class="siaDC09-zone" id="siaDC09-zone-content">
											<h4 class="siaDC09-zone-title">{{Contenu envoyé avec l'alarme (photo / vidéo)}}</h4>
											<div class="siaDC09-row">
												<div class="siaDC09-field">
													<label class="siaDC09-label">{{Format du lien de la photo}}</label>
													<select class="eqLogicAttr form-control siaDC09-media-field siaDC09-profile-field" data-l1key="configuration" data-l2key="media_snapshot_format">
														<option value="V">Video Verification Link (V)</option>
														<option value="U">URL Multimedia Direct (U)</option>
													</select>
												</div>
												<div class="siaDC09-field">
													<label class="siaDC09-label">{{Format du lien de la vidéo}}</label>
													<select class="eqLogicAttr form-control siaDC09-media-field siaDC09-profile-field" data-l1key="configuration" data-l2key="media_clip_format">
														<option value="V">Video Verification Link (V)</option>
														<option value="U">URL Multimedia Direct (U)</option>
													</select>
												</div>
											</div>
											<p class="siaDC09-help">{{Formats possibles : Video Verification Link (V) / URL Multimedia Direct (U)}}</p>
											<div class="siaDC09-field siaDC09-w-full" id="siaDC09-media-single-tag-group" style="margin-top:14px;">
												<!-- media_single_tag stays the saved field; the radios below drive it -->
												<input type="checkbox" class="eqLogicAttr siaDC09-media-field siaDC09-profile-field" data-l1key="configuration" data-l2key="media_single_tag" style="display:none;" aria-hidden="true" tabindex="-1">
												<div id="siaDC09-ext-choice">
													<span class="siaDC09-label">{{Quand photo ET vidéo ont le même format :}}</span>
													<div class="radio"><label><input type="radio" name="siaDC09-ext-mode" class="siaDC09-ext-radio siaDC09-media-field siaDC09-profile-field" value="1"> {{une seule extension pour les deux liens}}</label>
														<br><code id="siaDC09-ext-example-single"></code></div>
													<div class="radio"><label><input type="radio" name="siaDC09-ext-mode" class="siaDC09-ext-radio siaDC09-media-field siaDC09-profile-field" value="0"> {{une extension par lien}}</label>
														<br><code id="siaDC09-ext-example-multi"></code></div>
												</div>
												<p class="siaDC09-help" id="siaDC09-media-single-tag-help" style="display:none;">{{Disponible seulement si photo et vidéo sont envoyées avec le même format.}}</p>
											</div>
										</div>

										<!-- Serveur FTPS (story 18.11) : only under FTPS with the media box ticked; never a profile field, never locked -->
										<div class="siaDC09-zone" id="siaDC09-ftps-card" style="display:none;">
											<h4 class="siaDC09-zone-title">{{Serveur FTPS}}</h4>
											<p class="siaDC09-summary">{{Réglages propres à votre installation : jamais fixés par le profil.}}</p>
											<div class="siaDC09-row">
												<div class="siaDC09-field siaDC09-w-input">
													<label class="siaDC09-label" for="siaDC09-ftps-host">{{Serveur *}}</label>
													<input type="text" id="siaDC09-ftps-host" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="ftps_host" placeholder="ftp.exemple.fr">
												</div>
												<div class="siaDC09-field siaDC09-w-narrow">
													<label class="siaDC09-label" for="siaDC09-ftps-port">{{Port *}}</label>
													<input type="number" id="siaDC09-ftps-port" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="ftps_port" placeholder="21">
												</div>
											</div>
											<div class="siaDC09-row">
												<div class="siaDC09-field siaDC09-w-input">
													<label class="siaDC09-label" for="siaDC09-ftps-user">{{Utilisateur *}}</label>
													<input type="text" id="siaDC09-ftps-user" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="ftps_user" autocomplete="off">
												</div>
												<div class="siaDC09-field siaDC09-w-input">
													<label class="siaDC09-label" for="siaDC09-ftps-password">{{Mot de passe *}}</label>
													<input type="password" id="siaDC09-ftps-password" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="ftps_password" autocomplete="new-password">
												</div>
											</div>
											<div class="siaDC09-field siaDC09-w-input" style="margin-top:14px;">
												<label class="siaDC09-label" for="siaDC09-ftps-folder">{{Dossier distant}}</label>
												<input type="text" id="siaDC09-ftps-folder" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="ftps_folder">
												<p class="siaDC09-help">{{Laissez vide pour déposer à la racine du compte. Le dossier doit exister.}}</p>
											</div>
											<div class="siaDC09-field siaDC09-w-full" style="margin-top:14px;">
												<span class="siaDC09-label">{{Certificat du serveur}}</span>
												<!-- The radios add no config key: an empty fingerprint is « reconnu », a filled one « auto-signé » -->
												<div class="radio"><label><input type="radio" class="siaDC09-ftps-cert-radio" name="siaDC09-ftps-cert" value="public"> {{Certificat reconnu}}</label>
													<p class="siaDC09-help">{{Serveur avec un certificat d'une autorité publique (Let's Encrypt...).}}</p></div>
												<div class="radio"><label><input type="radio" class="siaDC09-ftps-cert-radio" name="siaDC09-ftps-cert" value="selfsigned"> {{Certificat auto-signé}}</label></div>
												<div class="siaDC09-field siaDC09-w-input" id="siaDC09-ftps-fingerprint-group" style="display:none;">
													<label class="siaDC09-label" for="siaDC09-ftps-fingerprint">{{Empreinte SHA-256 du certificat}}</label>
													<input type="text" id="siaDC09-ftps-fingerprint" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="ftps_cert_fingerprint">
												</div>
											</div>
										</div>

										<!-- Supervision de la liaison -->
										<div class="siaDC09-zone" id="siaDC09-zone-supervision">
											<h4 class="siaDC09-zone-title">{{Supervision de la liaison}}</h4>
											<p class="siaDC09-summary">{{Votre alarme signale régulièrement à la centrale qu'elle fonctionne.}}</p>
											<div class="siaDC09-row">
												<div class="siaDC09-field">
													<label class="siaDC09-label">{{Message de vie (trame de supervision)}}</label>
													<select class="eqLogicAttr form-control siaDC09-profile-field" data-l1key="configuration" data-l2key="supervision_format">
														<option value="none">{{Aucune}}</option>
														<option value="sia-dcs">SIA-DCS</option>
														<option value="null">NULL</option>
													</select>
												</div>
												<div class="siaDC09-field">
													<label class="siaDC09-label">{{Toutes les (secondes)}}</label>
													<input type="number" class="eqLogicAttr form-control siaDC09-profile-field" data-l1key="configuration" data-l2key="supervision_interval" placeholder="60">
												</div>
											</div>
											<div class="siaDC09-row">
												<div class="siaDC09-field">
													<label class="siaDC09-checkbox-box"><input type="checkbox" class="eqLogicAttr siaDC09-profile-field" data-l1key="configuration" data-l2key="rp_enabled">{{Test cyclique (RP)}}</label>
												</div>
												<div class="siaDC09-field">
													<label class="siaDC09-label">{{Toutes les (secondes)}}</label>
													<input type="number" class="eqLogicAttr form-control siaDC09-profile-field" data-l1key="configuration" data-l2key="rp_interval" placeholder="60" min="60" max="86400">
												</div>
											</div>
											<p class="siaDC09-help">{{Au moins un des deux doit être actif, sinon la centrale ne saura pas si l'alarme est en panne.}}</p>
											<div class="siaDC09-row" style="margin-top:14px;">
												<div class="siaDC09-field">
													<label class="siaDC09-label">{{Tentatives de reconnexion}}</label>
													<input type="number" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="retry_count" placeholder="6">
												</div>
												<div class="siaDC09-field">
													<label class="siaDC09-label">{{Délai de reconnexion (s)}}</label>
													<input type="number" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="reconnect_delay" placeholder="30">
												</div>
											</div>
										</div>
									</div><!-- /#siaDC09-advanced -->

									<!-- Advanced-option errors found by « Relancer le test » -->
									<div id="siaDC09-step2-errors" class="alert alert-danger siaDC09-banner-error" role="alert" style="display:none;"></div>

									<!-- Buttons -->
									<div class="siaDC09-actions">
										<a class="btn btn-default siaDC09-actions-left" id="bt_step2Back"><i class="fas fa-arrow-left"></i> {{Modifier la centrale}}</a>
										<!-- The single test button; its label and look are set by JS (Lancer / Relancer / en cours) -->
										<a class="btn btn-success" id="bt_step2Retest"><i class="fas fa-play"></i> <span id="bt_step2Retest-label">{{Lancer le test}}</span></a>
										<!-- One right-hand slot: Suivant only when every test passed, otherwise Ignorer (never both) -->
										<a class="btn btn-default" id="bt_step2Skip"><i class="fas fa-forward"></i> {{Ignorer}}</a>
										<a class="btn btn-success" id="bt_step2Next" style="display:none;"><i class="fas fa-arrow-right"></i> {{Suivant}}</a>
									</div>
								</div><!-- /#siaDC09-step2 -->

								<!-- Step 3: zones and critical alerts (former steps 3 and 4) -->
								<div id="siaDC09-step3" class="siaDC09-step" style="display:none;">
									<div class="siaDC09-zone" id="siaDC09-zone-zones">
										<h4 class="siaDC09-zone-title">{{Vos zones d'alarme}}</h4>
										<div id="siaDC09-step3-warning" class="alert alert-warning siaDC09-test-warning" style="display:none;">
											<!-- One line per test not passed, filled by JS when « Ignorer » is pressed (story 18.12) -->
											<p id="siaDC09-step3-warning-sia" style="display:none;margin:0;"><i class="fas fa-exclamation-triangle"></i> <span></span></p>
											<p id="siaDC09-step3-warning-ftps" style="display:none;margin:0;"><i class="fas fa-exclamation-triangle"></i> <span></span></p>
										</div>
										<div id="siaDC09-step3-nozone" class="alert alert-warning siaDC09-test-warning" style="display:none;">
											<i class="fas fa-exclamation-triangle"></i> {{Aucune zone détectée — configurez d'abord votre plugin alarme.}}
										</div>
										<div id="siaDC09-step3-nocamera" class="alert alert-warning siaDC09-test-warning" style="display:none;">
											<i class="fas fa-exclamation-triangle"></i> {{Aucune caméra Frigate détectée — installez et configurez le plugin Frigate NVR pour rattacher un aperçu aux alarmes.}}
										</div>
										<div id="siaDC09-step3-errors" class="alert alert-danger siaDC09-banner-error" role="alert" style="display:none;"></div>
											<div class="siaDC09-row" style="margin-bottom:10px;">
												<div class="siaDC09-field siaDC09-w-wide">
													<label class="siaDC09-label" for="siaDC09-alarm-select">{{Équipement Alarme}}</label>
													<select id="siaDC09-alarm-select" class="form-control eqLogicAttr" data-l1key="configuration" data-l2key="alarm_eqlogic_id">
														<option value="">{{(choisir)}}</option>
<?php
foreach ((eqLogic::byType('alarm') ?: []) as $siaDC09AlarmEq) {
	echo '<option value="' . (int) $siaDC09AlarmEq->getId() . '">' . htmlspecialchars($siaDC09AlarmEq->getHumanName(true)) . '</option>';
}
?>
													</select>
													<a class="btn btn-primary btn-sm" id="bt_linkAlarm" style="margin-top:6px;"><i class="fas fa-link"></i> {{Lier au plugin Alarme}}</a>
													<p class="siaDC09-help">{{Écrit les commandes siaDC09 dans les actions de l'équipement Alarme choisi (armement, désarmement, remise à zéro, alarme intrusion, prefetch). Vous pouvez relier à nouveau après un changement de zones.}}</p>
													<p class="siaDC09-help"><i class="fas fa-exclamation-triangle"></i> {{Fermez la page de cet équipement Alarme avant de lier : un enregistrement depuis cette page écraserait le résultat.}}</p>
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
										<p class="siaDC09-help">
											<i class="fas fa-info-circle"></i> {{Le prefetch Frigate est câblé automatiquement pour les zones qui ont une caméra, à la liaison avec le plugin Alarme.}}
										</p>
										<div class="siaDC09-row" style="margin-top:14px;">
											<div class="siaDC09-field siaDC09-w-wide">
												<label class="siaDC09-label">{{Numéro utilisateur SIA}}</label>
												<input type="number" min="1" max="999" class="eqLogicAttr form-control" data-l1key="configuration" data-l2key="sia_user_number" placeholder="1">
												<p class="siaDC09-help">{{Numéro déclaré à la centrale pour identifier l'utilisateur Jeedom lors d'une annulation/désarmement.}}</p>
											</div>
										</div>
										<p class="siaDC09-help">
											<i class="fas fa-info-circle"></i> {{Le bouton « Lier au plugin Alarme » câble les commandes à votre place —}} <a href="https://hlehoux2021.github.io/siadc09/fr_FR/#câbler-le-plugin-alarme" target="_blank" rel="noopener">{{voir la documentation de câblage}}</a>.
										</p>
									</div>

									<div class="siaDC09-zone" id="siaDC09-zone-alerts">
										<h4 class="siaDC09-zone-title">{{Alertes critiques}}</h4>
										<p class="siaDC09-help" style="margin-top:0;">
											{{En cas de problème grave (supervision perdue, alarme non transmise), le plugin doit prévenir quelqu'un.}}
										</p>
										<div class="siaDC09-row" style="margin-top:14px;">
											<div class="siaDC09-field siaDC09-w-input">
												<label class="siaDC09-label" for="siaDC09_notifyKind">{{Type de notification}}</label>
												<select class="eqLogicAttr form-control" id="siaDC09_notifyKind"
														data-l1key="configuration" data-l2key="sia_notify_kind">
													<option value="cmd">{{Commande d'un équipement (SMS, Telegram, push…)}}</option>
													<option value="internal">{{Action interne Jeedom}}</option>
												</select>
											</div>
										</div>
										<div class="siaDC09-row siaDC09-notify-cmd">
											<div class="siaDC09-field siaDC09-w-input">
												<label class="siaDC09-label">{{Commande de notification}}</label>
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
										<div class="siaDC09-row siaDC09-notify-internal">
											<div class="siaDC09-field siaDC09-w-input">
												<label class="siaDC09-label" for="siaDC09_notifyInternal">{{Action interne}}</label>
												<select class="eqLogicAttr form-control" id="siaDC09_notifyInternal"
														data-l1key="configuration" data-l2key="sia_notify_internal">
													<option value="">{{Choisissez une action}}</option>
													<option value="message">{{message — ajouter au centre de messages Jeedom}}</option>
													<option value="scenario">{{scenario — lancer un scénario}}</option>
												</select>
											</div>
										</div>
										<div class="siaDC09-row siaDC09-notify-scenario">
											<div class="siaDC09-field siaDC09-w-input">
												<label class="siaDC09-label" for="siaDC09_notifyScenario">{{Scénario à lancer}}</label>
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
										<div id="siaDC09-notify-error" class="alert alert-danger siaDC09-banner-error" role="alert" style="display:none;">
											<i class="fas fa-exclamation-circle"></i> {{Veuillez sélectionner une commande. Vous pouvez toujours utiliser la messagerie Jeedom.}}
										</div>
										<div id="siaDC09-notify-error-internal" class="alert alert-danger siaDC09-banner-error" role="alert" style="display:none;">
											<i class="fas fa-exclamation-circle"></i> {{Veuillez choisir l'action interne à exécuter.}}
										</div>
										<div id="siaDC09-notify-error-scenario" class="alert alert-danger siaDC09-banner-error" role="alert" style="display:none;">
											<i class="fas fa-exclamation-circle"></i> {{Veuillez choisir le scénario à lancer.}}
										</div>
									</div>

									<div class="siaDC09-actions">
										<a class="btn btn-success" id="bt_step3Finish"><i class="fas fa-check"></i> {{Terminer}}</a>
									</div>
								</div><!-- /#siaDC09-step3 -->
							</div><!-- /#siaDC09-wizard -->

							<!-- CONFIG MODE (sia_wizard_step == 4: wizard complete) -->
							<div id="siaDC09-config-summary" style="display:none;">
								<legend><i class="fas fa-info-circle"></i> {{Configuration active}}</legend>
								<div class="well well-sm" style="margin-top:10px;">
									<strong>{{Connexion}}</strong>
									<div id="siaDC09-summary-connection" style="margin:8px 0 12px 10px;"></div>
									<strong>{{Levée de doute}}</strong>
									<div id="siaDC09-summary-media" style="margin:8px 0 12px 10px;"></div>
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

<?php include_file('desktop', 'siaDC09', 'css', 'siaDC09'); ?>
<?php include_file('desktop', 'siaDC09', 'js', 'siaDC09'); ?>
<?php include_file('core', 'plugin.template', 'js'); ?>
