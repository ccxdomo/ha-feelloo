<p align="center">
  <img src="https://raw.githubusercontent.com/ccxdomo/ha-feelloo/main/icon.png" width="128" height="128" alt="Logo Feelloo">
</p>

# Intégration Feelloo pour Home Assistant

> 🇬🇧 English version: [README.md](README.md)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Intégration personnalisée pour les traceurs GPS pour chats [Feelloo](https://feelloo.com) dans Home Assistant.

## Fonctionnalités

- **Suivi GPS en temps réel** — position en direct sur la carte Home Assistant
- **Suivi d'activité** — pourcentages de repos, de calme et d'action, avec historique horaire
- **Sessions de territoire** — suivi des sorties avec heures de début et de fin, et nombre de sessions
- **Batterie et état de charge** — ne ratez plus jamais une batterie faible
- **Détection de présence** — état à la maison / absent / à portée
- **Bouton de sonnerie** — localisez votre chat en déclenchant la sonnerie du collier
- **Mode recherche étendue** — suivez l'activation et l'expiration de la recherche
- **Polling rapide dynamique** — quand le mode Petite Souris est activé, le polling passe à 1 minute pour un suivi GPS et un signal en temps réel
- **Contrôle du polling** — désactivez le polling automatique ou changez sa cadence (1 à 1440 minutes), rafraîchissez à la demande, et consultez l'âge des données — voir [Contrôle du polling](#contrôle-du-polling)

## Installation

### HACS (recommandé)

1. Ouvrez HACS dans Home Assistant
2. Allez dans **Intégrations**
3. Cliquez sur le menu (⋮) et choisissez **Dépôts personnalisés**
4. Ajoutez `https://github.com/ccxdomo/ha-feelloo` avec la catégorie **Integration**
5. Cliquez sur **Télécharger**
6. Redémarrez Home Assistant

### Manuelle

1. Copiez le dossier `custom_components/feelloo` dans le répertoire `config/custom_components` de votre Home Assistant
2. Redémarrez Home Assistant

## Configuration

1. Allez dans **Paramètres** → **Appareils et services** → **Ajouter une intégration**
2. Recherchez **Feelloo**
3. Saisissez l'adresse e-mail et le mot de passe de votre compte Feelloo

Vos chats et leurs données seront détectés automatiquement.

## Architecture

L'intégration utilise **six coordinateurs de mise à jour** pour un polling optimal :

| Coordinateur | Point d'accès | Intervalle |
|------------|----------|----------|
| Principal | `/users/cats` + `/users/cats/{cat_id}` | **Configurable** (5 minutes par défaut ; 1 min avec le polling rapide Petite Souris) |
| Activité | `/users/cats/{cat_id}/activity?period_type=day` | 15 minutes |
| Activité hebdo | `/users/cats/{cat_id}/activity?period_type=week` | 1 heure |
| Activité mensuelle | `/users/cats/{cat_id}/activity?period_type=month` | 6 heures |
| Territoire | `/users/cats/{cat_id}/territory/paths` | 15 minutes |
| Session | `/users/cats/{cat_id}/territory/paths/{session_id}` | 30 minutes |

Tous les coordinateurs partagent un unique gestionnaire d'authentification Firebase, avec un rafraîchissement automatique du jeton toutes les 50 minutes (toujours actif, même quand le polling est désactivé, afin que les récupérations à la demande puissent toujours s'authentifier).

### Polling rapide dynamique

Quand l'interrupteur **Petite Souris** est activé pour un chat :
- L'intégration force temporairement le **coordinateur principal sur un intervalle de 1 minute** (l'« override Petite Souris ») — c'est ce qui fait réellement fonctionner le mode, que le polling automatique soit activé ou non
- Cela concerne la position GPS, la force du signal, la batterie et toutes les entités du coordinateur principal
- Quand le mode se termine (interrupteur sur OFF ou expiration côté serveur), **vos réglages de polling sont restaurés à l'identique** — y compris le retour à « désactivé » si c'est ce que vous aviez configuré
- Plusieurs chats partagent un seul override : il s'active avec le premier chat et se termine avec le dernier ; prolonger la durée ou l'activer deux fois ne change rien (idempotent)
- **Si vous modifiez un réglage de polling manuellement pendant que le mode est actif, votre action manuelle l'emporte** — le boost temporaire à 1 minute s'arrête et ne se réengagera pas tant que le mode n'aura pas été désactivé puis réactivé. Tant que le polling reste activé, le mode continue de recevoir des mises à jour à 1 minute via la minuterie de polling rapide historique
- Votre préférence configurée n'est jamais modifiée par le mode : elle réside dans les options de l'entrée de configuration, et l'override temporaire est transitoire (en mémoire ; après un redémarrage de Home Assistant, il est reconstruit depuis l'état du mode côté cloud Feelloo)

**Vous voyez l'intervalle passer à 1 minute tout seul ?** C'est l'override à l'œuvre : tant qu'un chat a la Petite Souris active, le poller principal tourne à 1 minute, et vos réglages enregistrés reprennent automatiquement à la fin du mode (interrupteur sur OFF ou expiration). Pour le confirmer, consultez l'attribut `petite_souris_override` du capteur **Last Update** (`true` pendant le boost) ou la ligne de journal `Petite Souris active: temporary 1-minute polling override engaged`. L'interrupteur **Automatic Polling** se met visiblement sur ON pendant toute la durée du boost — étiqueté *(Petite Souris)* avec une icône d'horloge rapide — et revient à votre état enregistré quand le mode se termine ; le nombre **Polling Interval** continue d'afficher votre préférence enregistrée (avec la cadence temporaire dans son attribut `effective_polling_interval_minutes`).

## Contrôle du polling

Vous contrôlez la fréquence (et l'activation) du polling automatique vers le cloud Feelloo. Tous les réglages se trouvent sur l'appareil **Feelloo** (un jeu par compte configuré) et dans le flux d'options de l'intégration (Paramètres → Appareils et services → Feelloo → Configurer).

### Réglages

| Réglage | Emplacement | Plage / Défaut |
|---------|-------|------------------|
| **Automatic Polling** (interrupteur, config) | Appareil Feelloo | ON (défaut) / OFF |
| **Polling Interval** (nombre, config) | Appareil Feelloo | 1 à 1440 minutes, défaut **5** |

Les deux réglages sont aussi modifiables dans le flux d'options, et tous deux sont persistés dans les options de l'entrée de configuration (ils survivent aux redémarrages). Les changements s'appliquent à chaud — aucun redémarrage de Home Assistant ni rechargement de l'intégration n'est nécessaire.

### Ce que signifie « polling désactivé »

- Le **coordinateur principal** (`/users/cats`) cesse de récupérer des données de lui-même. Après au plus une récupération déjà planifiée, plus aucun appel cloud automatique n'est effectué pour les données des chats.
- **Tous les autres coordinateurs conservent leur cadence fixe** (activité 15 min / hebdo 1 h / mensuel 6 h / territoire 15 min / session 30 min).
- **Le rafraîchissement du jeton (maintenance de l'authentification) continue de tourner** (~50 min) afin que les rafraîchissements manuels et les commandes Petite Souris fonctionnent toujours.
- **Petite Souris + polling désactivé** : activer la Petite Souris alors que le polling automatique est désactivé **réactive temporairement le polling à 1 minute** pour que le mode suive réellement votre chat (une ligne de journal le signale). Quand le mode se termine, le polling est désactivé à nouveau automatiquement — votre préférence est mémorisée dans les options de l'entrée et n'est jamais modifiée. Si vous changez manuellement un réglage de polling pendant que le mode est actif, votre action manuelle l'emporte (le boost temporaire s'arrête) — mettre l'interrupteur **Automatic Polling** sur OFF pendant le boost l'arrête immédiatement et l'interrupteur bascule visiblement sur OFF.
- **L'override est visible sur l'interrupteur de polling** : pendant le boost, l'interrupteur **Automatic Polling** indique **ON** (le polling tourne réellement, à 1 minute), affiche une icône d'horloge rapide, et est étiqueté *Automatic Polling (Petite Souris)* — un contrôle qui semblerait désactivé alors que les données circulent ne peut plus se produire. Ses attributs exposent à la fois votre préférence enregistrée (`saved_polling_enabled`, `saved_polling_interval_minutes`) et ce qui est actuellement en vigueur (`effective_polling_enabled`, `effective_polling_interval_minutes`). Quand le mode se termine, l'interrupteur revient automatiquement à votre état enregistré. Le nombre **Polling Interval** continue d'afficher votre préférence enregistrée, la cadence temporaire étant visible dans son attribut `effective_polling_interval_minutes`.
- **Le capteur Last Update reste la source de vérité pour l'override** : pendant le boost, ses attributs `polling_enabled` / `polling_interval_minutes` affichent la cadence temporaire de 1 minute et `petite_souris_override` vaut `true`.
- **Les entités conservent leurs dernières valeurs connues** : sans rafraîchissement, il n'y a pas d'échec, donc rien ne passe en « indisponible » simplement parce que le polling est désactivé. Les vrais échecs (réseau coupé, identifiants invalides) remontent exactement comme avant.
- Le capteur de diagnostic **Last Update** se fige à la dernière récupération réussie, de sorte que l'âge des données reste toujours visible ; ses attributs affichent les réglages de polling en cours.
- La désactivation du polling applique un rafraîchissement immédiat temporisé lors de la **réactivation** ou d'un changement d'intervalle tant que le polling est actif (des données fraîches arrivent sous ~10 s), afin que les changements prennent effet sans attendre l'ancienne minuterie.

### Rafraîchissement manuel

Le bouton **Refresh Data** (un par compte, sur l'appareil Feelloo) récupère tout immédiatement — les données principales des chats d'abord, puis l'activité, l'activité hebdomadaire et mensuelle, le territoire et les données de session. Il fonctionne que le polling soit activé ou non. Les appuis rapprochés sont sans danger (ils sont fusionnés).

Exemple d'automatisation :

```yaml
automation:
  - alias: "Rafraîchir quand je rentre"
    trigger:
      - platform: zone
        entity_id: person.owner
        zone: zone.home
        event: enter
    action:
      - service: button.press
        target:
          entity_id: button.feelloo_refresh_data
```

### Identifiants dans le flux d'options

Le flux d'options ne demande plus votre mot de passe simplement pour changer les réglages de polling — laissez le mot de passe **vide pour conserver vos identifiants actuels**. Saisir un nouvel e-mail (avec mot de passe) ou un nouveau mot de passe les valide toujours auprès de Firebase et les applique comme avant.

## Entités

Pour chaque chat détecté, les entités suivantes sont créées :

### Capteurs binaires
- **Home** — si le chat est à la maison
- **In Range** — si le collier est à portée LoRa
- **Gateway Online** — si la passerelle est connectée
- **Charging** — si le collier est en charge
- **Is Ringing** — si le collier sonne actuellement
- **Battery Low** — alerte de batterie faible
- **Extended Search** — si le mode recherche étendue est activé

### Capteurs
- **Signal Strength** — force du signal LoRa (%) du collier vers la passerelle
  - Attribut : `rssi_dbm` — valeur RSSI brute
- **Battery** — niveau de batterie (%)
- **Latitude** / **Longitude** — dernières coordonnées GPS connues
- **GPS Precision** — précision en mètres
- **Last Seen** — horodatage de la dernière mise à jour de position
- **Presence Time** — horodatage de la dernière détection de présence
- **Activity** — activité dominante actuelle (sommeil / calme / actif)
  - Attribut : `history` — répartition horaire complète sur 24 heures
- **Activity Rest** — pourcentage de repos (%)
- **Activity Calm** — pourcentage de calme (%)
- **Activity Action** — pourcentage d'action (%)
  - Attribut : `history` — répartition horaire complète sur 24 heures
- **Extended Search Expiration** — moment d'expiration de la recherche étendue
- **Last Outing Start** — horodatage du début de la dernière session de territoire
- **Last Outing End** — horodatage de la fin de la dernière session de territoire
- **Outing Count** — nombre total de sessions de territoire

### Traceur d'appareil
- **Tracker** — position GPS sur la carte Home Assistant
  - `source_type` : GPS
  - `latitude` / `longitude` : dernières coordonnées connues
  - `location_accuracy` : rayon de précision en mètres (cercle sur la carte)
  - État : `home` si `presence.status.in_range` est vrai, sinon `not_home`
  - Attributs :
    - `last_seen` : horodatage ISO de la dernière mise à jour de position
    - `precision_meter` : précision GPS en mètres
  - Icône : `mdi:cat`
  - **Photo personnalisée** : voir [Images personnalisées des chats](#images-personnalisées-des-chats) ci-dessous

### Images personnalisées des chats

Vous pouvez afficher une photo personnalisée pour chaque chat sur la carte et dans la carte du traceur d'appareil.

**Comment ça marche :**
- Au démarrage, l'intégration vérifie si un fichier image existe pour chaque chat
- S'il est trouvé, elle définit automatiquement `entity_picture` sur le traceur d'appareil
- Aucun appel API ni stockage cloud nécessaire — uniquement des fichiers locaux

**Où placer l'image :**

Créez le dossier et copiez la photo de votre chat :

```bash
mkdir -p /config/www/feelloo
cp /chemin/vers/votre/photo.jpg /config/www/feelloo/{nom_du_chat}.jpg
```

Remplacez `{nom_du_chat}` par le nom de votre chat en minuscules, les espaces remplacés par des underscores.

**Nommage des fichiers :**
- Le nom du fichier doit correspondre au **nom du chat en minuscules avec des underscores** (espaces remplacés par des underscores)
- Exemple : chat nommé `Moustache` → fichier `moustache.jpg` ou `moustache.png`
- Exemple : chat nommé `Moustache Le Chat` → fichier `moustache_le_chat.jpg`

**Formats pris en charge :** `.jpg` et `.png`

**Résolution recommandée :** 400×400 pixels (ratio 1:1) pour un affichage optimal sur la carte et les cartes d'entité

**Détection dynamique :** l'intégration vérifie la présence du fichier image à chaque rafraîchissement du coordinateur (toutes les 5 minutes, ou toutes les minutes quand la Petite Souris est active). Aucun redémarrage nécessaire — ajoutez simplement l'image et attendez le prochain rafraîchissement.

**Résultat :** le traceur d'appareil affichera la photo de votre chat au lieu de l'icône `mdi:cat` par défaut, sur la carte et dans les cartes d'entité.

### Interrupteurs
- **Petite Souris** — active/désactive le mode recherche étendue avec polling rapide
  - Quand activé : l'intervalle de polling passe à **1 minute** pour un GPS et un signal en temps réel (sauf si le polling automatique est désactivé)
  - Quand désactivé : retour au polling normal
  - Chaque chat a sa propre minuterie indépendante
- **Automatic Polling** (config) — sur l'appareil **Feelloo** ; ON = le poller principal tourne automatiquement (défaut), OFF = aucun polling automatique (voir [Contrôle du polling](#contrôle-du-polling)). Tant qu'un override Petite Souris est actif, l'interrupteur indique ON (le polling tourne à 1 minute) avec un libellé *(Petite Souris)* et une icône d'horloge rapide ; ses attributs exposent votre préférence enregistrée et l'état effectif

### Nombres
- **Petite Souris Duration** — durée en heures utilisée quand la Petite Souris est activée
- **Polling Interval** (config) — sur l'appareil **Feelloo** ; cadence du poller principal en minutes (1 à 1440, défaut 5). Tant qu'un override Petite Souris est actif, la valeur affichée reste votre préférence enregistrée et l'attribut `effective_polling_interval_minutes` montre la cadence temporaire de 1 minute

### Bouton
- **Ring** — déclenche la sonnerie du collier (uniquement si `can_ring` est vrai)
- **Refresh Data** — sur l'appareil **Feelloo** ; récupère immédiatement toutes les données Feelloo (tous les coordinateurs), quel que soit l'état du polling

### Capteurs (au niveau de l'appareil, sur l'appareil hub **Feelloo**)
- **Last Update** (diagnostic) — horodatage de la dernière récupération réussie des chats ; se fige quand le polling est désactivé, afin que l'âge des données reste visible. Attributs : `polling_enabled`, `polling_interval_minutes` (l'état **effectif** — pendant un override Petite Souris, ils affichent la cadence temporaire de 1 minute), et `petite_souris_override` (`true` pendant que l'override force temporairement le polling à 1 minute)

## Registre des appareils

Chaque chat est enregistré comme appareil avec :
- Nom : le nom du profil du chat
- Fabricant : Feelloo
- Modèle : Cat Tracker

Chaque compte configuré reçoit également un appareil hub **Feelloo** (modèle : Account) hébergeant les entités du compte : **Automatic Polling**, **Polling Interval**, **Refresh Data** et **Last Update**.

## Prérequis

- Home Assistant 2024.12.0 ou plus récent (le flux d'options s'appuie sur la classe de base `OptionsFlow` qui résout `config_entry`, introduite dans HA 2024.12)

## Support

Pour les problèmes et les demandes de fonctionnalités, utilisez le [suivi des tickets GitHub](https://github.com/ccxdomo/ha-feelloo/issues).
