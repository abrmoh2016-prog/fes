/* Horaires de prière — lit window.HORAIRES_MOIS (data/horaires-AAAA-MM.js, un fichier par mois), aucun appel réseau. */
(function () {
  'use strict';

  var moisDispo = window.HORAIRES_MOIS || [];
  var root = document.getElementById('prieres');
  if (!moisDispo.length || !root) return;

  // Mois affiché : celui de la date du jour (choisirMois), sinon le dernier mois publié.
  var data = moisDispo[moisDispo.length - 1];

  var NOMS = ['الصبح', 'الشروق', 'الظهر', 'العصر', 'المغرب', 'العشاء'];
  var JOURS = ['الأحد', 'الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت'];
  var MOIS = ['يناير', 'فبراير', 'مارس', 'أبريل', 'ماي', 'يونيو', 'يوليوز', 'غشت', 'شتنبر', 'أكتوبر', 'نونبر', 'دجنبر'];
  var VILLE_DEFAUT = 1; // الرباط
  // Codes retirés car en double : ancien code -> code conservé (anciens liens ?ville=N).
  var ALIAS = { 303: 94 }; // تاهلة
  var CLE = 'habous-ville';

  var select = document.getElementById('ville');
  var dateEl = document.getElementById('prayer-date');
  var todayEl = document.getElementById('today');
  var alertEl = document.getElementById('prayer-alert');

  // Heure légale du Maroc = GMT depuis le 20/09/2026 (décret 2.26.530).
  // Calculée depuis l'UTC plutôt que via 'Africa/Casablanca' : les navigateurs
  // dont la base de fuseaux n'est pas à jour y appliquent encore GMT+1.
  var DECALAGE_MAROC_MINUTES = 0;

  function maintenantMaroc() {
    var d = new Date(Date.now() + DECALAGE_MAROC_MINUTES * 60000);
    return {
      annee: d.getUTCFullYear(), mois: d.getUTCMonth() + 1, jour: d.getUTCDate(),
      minutes: d.getUTCHours() * 60 + d.getUTCMinutes()
    };
  }

  // Date hégirienne d'après les débuts de mois annoncés (data/hijri.js), sans calcul astronomique.
  // Renvoie null si la date sort des mois connus.
  var HIJRI = window.HIJRI;
  function dateHijri(a, m, j) {
    if (!HIJRI) return null;
    var t = Date.UTC(a, m - 1, j);
    for (var i = HIJRI.mois.length - 1; i >= 0; i--) {
      var e = HIJRI.mois[i];
      var p = e.debut.split('-');
      var n = Math.round((t - Date.UTC(+p[0], +p[1] - 1, +p[2])) / 86400000) + 1;
      if (n < 1) continue;
      if (n > (e.duree || 30)) return null;
      return {
        jour: n,
        nom: HIJRI.noms[e.mois - 1],
        annee: e.annee,
        // 30e jour d'un mois dont la durée n'est pas encore annoncée
        incertain: e.duree === null && n === 30
      };
    }
    return null;
  }

  function texteHijri(h, avecAnnee) {
    if (!h) return '—';
    if (h.incertain) return 'حسب نتيجة المراقبة';
    return h.jour + ' ' + h.nom + (avecAnnee ? ' ' + h.annee + 'هـ' : '');
  }

  function enMinutes(hhmm) {
    var t = hhmm.split(':');
    return (+t[0]) * 60 + (+t[1]);
  }

  function jourSemaine(a, m, j) {
    return new Date(Date.UTC(a, m - 1, j)).getUTCDay();
  }

  function lireStockage() {
    try { return window.localStorage.getItem(CLE); } catch (e) { return null; }
  }
  function ecrireStockage(v) {
    try { window.localStorage.setItem(CLE, v); } catch (e) { /* stockage indisponible */ }
  }

  function trouverVille(code) {
    for (var i = 0; i < data.villes.length; i++) {
      if (data.villes[i].c === code) return data.villes[i];
    }
    return null;
  }

  // Ville initiale : ?ville=N (compatible avec les anciens liens), sinon dernier choix, sinon Rabat.
  function villeInitiale() {
    var m = /[?&]ville=(\d+)/.exec(window.location.search);
    var candidats = [m && +m[1], +lireStockage(), VILLE_DEFAUT].map(function (c) { return ALIAS[c] || c; });
    for (var i = 0; i < candidats.length; i++) {
      if (candidats[i] && trouverVille(candidats[i])) return candidats[i];
    }
    return data.villes[0].c;
  }

  // Liste déroulante triée selon l'ordre de villes.json (même ordre que le site actuel).
  data.villes.forEach(function (v) {
    var o = document.createElement('option');
    o.value = v.c;
    o.textContent = v.n;
    select.appendChild(o);
  });

  var nbJours, moisLabel;

  function choisirMois(now) {
    data = moisDispo[moisDispo.length - 1];
    for (var i = 0; i < moisDispo.length; i++) {
      if (moisDispo[i].annee === now.annee && moisDispo[i].mois === now.mois) data = moisDispo[i];
    }
    nbJours = data.villes[0].h.length;
    moisLabel = MOIS[data.mois - 1] + ' ' + data.annee;
  }


  function afficher(code) {
    var now = maintenantMaroc();
    choisirMois(now);
    var ville = trouverVille(code);
    var dansLeMois = now.annee === data.annee && now.mois === data.mois;
    var jourIdx = dansLeMois ? now.jour - 1 : -1;

    // Jour affiché : aujourd'hui si couvert par les données, sinon le premier jour du mois publié.
    var idx = jourIdx >= 0 && jourIdx < nbJours ? jourIdx : 0;
    var h = ville.h[idx];
    var j = idx + 1;

    dateEl.innerHTML = '';
    var strong = document.createElement('strong');
    strong.textContent = JOURS[jourSemaine(data.annee, data.mois, j)] + ' ' + j + ' ' + MOIS[data.mois - 1] + ' ' + data.annee;
    dateEl.appendChild(document.createTextNode(ville.n + ' — '));
    dateEl.appendChild(strong);
    var hj = dateHijri(data.annee, data.mois, j);
    if (hj) {
      var hs = document.createElement('strong');
      hs.className = 'hijri';
      hs.textContent = texteHijri(hj, true);
      dateEl.appendChild(document.createTextNode(' · '));
      dateEl.appendChild(hs);
    }

    alertEl.hidden = jourIdx >= 0;
    if (!alertEl.hidden) {
      alertEl.textContent = 'المواقيت المعروضة خاصة بشهر ' + moisLabel + '، وسيتم تحيينها قريبا.';
    }

    // Prochaine prière (le lever du soleil n'est pas une prière).
    var prochaine = -1;
    if (jourIdx >= 0) {
      for (var k = 0; k < 6; k++) {
        if (k !== 1 && enMinutes(h[k]) > now.minutes) { prochaine = k; break; }
      }
    }

    todayEl.innerHTML = '';
    for (var p = 0; p < 6; p++) {
      var li = document.createElement('li');
      if (p === prochaine) li.className = 'next';
      li.innerHTML = '<span class="name"></span><span class="time"></span><span class="tag"></span>';
      li.children[0].textContent = NOMS[p];
      li.children[1].textContent = h[p];
      li.children[2].textContent = p === prochaine ? 'الصلاة القادمة' : '';
      todayEl.appendChild(li);
    }
  }

  var initiale = villeInitiale();
  select.value = String(initiale);
  afficher(initiale);

  select.addEventListener('change', function () {
    var code = +select.value;
    ecrireStockage(String(code));
    afficher(code);
  });

  // La surbrillance de la prochaine prière suit l'heure qui passe.
  window.setInterval(function () { afficher(+select.value); }, 60000);
})();
