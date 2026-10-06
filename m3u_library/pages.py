"""HTML pages for the M3U Library web UI.

The pages are plain (non-f) string constants so the inline CSS/JS needs no
Python escaping. German UI copy uses Swiss spelling (no ß). Both pages embed
the shared inline i18n block via the __I18N_INLINE__ placeholder; English is
the default, German can be selected in the settings.
"""

from __future__ import annotations

_I18N_JS = r"""
    const I18N = {
      en: {
        nav_library: "Library", nav_movies: "Movies", nav_series: "Series", nav_live: "Live TV",
        nav_favorites: "Favorites", nav_watched: "Watched", nav_settings: "Settings",
        sub_library: "Your movies and series. All in one place.",
        library_word: "Library",
        stat_entries: "items", stat_new: "New", stat_popular: "Popular", stat_trending: "Trending",
        aria_main_nav: "Main navigation",
        stat_upcoming: "Upcoming", stat_favorites: "Favorites", stat_continue: "Continue watching",
        search_placeholder: "Search title or group …",
        filter_type: "Type", filter_group: "Group", filter_sort: "Sorting",
        filter_language: "Language", all_languages: "All languages",
        lang_de: "German", lang_multi: "Multi", lang_en: "English", only_uhd: "4K",
        all_types: "All types", kind_movies: "Movies", kind_series: "Series", kind_live: "Live",
        all_groups: "All groups",
        sort_added: "Recently added", sort_title: "Title A–Z", sort_rating: "Rating", sort_release: "Release year",
        btn_update: "Update", btn_load_more: "Load more", btn_open: "Open", btn_open_tmdb: "View on TMDB", btn_load_now: "Load now",
        badge_new: "NEW", label_movie: "Movie", label_series: "Series", label_live: "Live", label_tmdb: "TMDB",
        watched_label: "Watched",
        ver_count: "{n} versions",
        version_pick_title: "Choose version",
        btn_close: "Close",
        favorites_toggle: "Toggle favorite",
        reset_continue: "Remove from Continue watching (resets watched progress)",
        episodes: "{n} episodes", episodes_progress: "{w} / {t} episodes watched",
        episodes_w_of_t: "{w} / {t} episodes",
        col_number: "Number", col_title: "Title", col_watched: "Watched", col_actions: "Actions",
        seasons: "Seasons",
        mark_episode_watched: "Mark episode as watched",
        poster_alt: "Poster of {title}",
        fallback_series: "SERIES", fallback_movie: "MOVIE", fallback_live: "LIVE", fallback_title: "TITLE",
        empty_all: "No items yet. Set up the M3U source and click «Update».",
        empty_trending: "No TMDB trends in your library right now.",
        empty_popular: "No popular titles from TMDB in your library right now.",
        empty_upcoming: "No upcoming movies from TMDB right now.",
        empty_continue: "Nothing started – begin a series and it will appear here.",
        empty_section: "Nothing marked in «{title}».",
        status_loading: "Loading library …",
        status_shown: "{shown} of {matched} shown",
        meta_error: "Error loading metadata: {msg}",
        meta_running: "Loading metadata in the background: {c} / {t}",
        meta_ready: "Metadata is up to date.",
        refresh_running: "Reloading library …",
        refresh_done: "Update finished – the library is up to date.",
        update_available: "Update available – the library could not be reloaded automatically.",
        source_check_title: "Check the source in Settings",
        src_not_configured: "M3U source not configured",
        src_unknown: "Source not checked yet",
        src_checking: "Checking source …",
        src_ok: "Source reachable",
        src_auth_failed: "Source authentication failed",
        src_unreachable: "Source unreachable",
        src_invalid: "No valid M3U playlist",
        src_empty: "Playlist without entries",
        entries_in_playlist: "Playlist valid · {n} entries",
        entries_count: "{n} entries",
        last_check: "Last check: {age}",
        age_now: "checked less than 1 min ago",
        age_minutes: "checked {n} min ago",
        age_hours: "checked {n} h ago",
        age_days: "checked {n} d ago",
        err_update_failed: "Update failed",
        err_login_required: "Login required – please sign in via Settings and try again.",
        err_load_failed: "Loading failed",
        err_metadata_status: "Metadata status failed",
        err_series_load: "Could not load the series",
        btn_next_episode: "Open next episode", btn_all_watched: "All episodes watched", btn_no_episode: "No episode available",
        btn_favorite: "Favorite", btn_favorited: "Favorited",
        settings_title: "Settings",
        back_to_library: "← Back to library",
        btn_logout: "Log out",
        auth_title_setup: "Initial setup – choose an admin password",
        auth_title_login: "Admin login",
        lbl_password: "Password", lbl_password2: "Repeat password",
        auth_hint_setup: "This password protects the settings and all admin actions. It is stored server-side as a bcrypt hash.",
        btn_login: "Log in", btn_create_password: "Create password",
        err_pw_mismatch: "Passwords do not match.",
        err_setup_failed: "Setup failed.",
        msg_password_created: "Password created.",
        err_login_failed: "Login failed.",
        msg_logged_in: "Logged in.",
        tab_library: "Library", tab_access: "Access", tab_security: "Security",
        h_source_metadata: "Source & metadata",
        lbl_m3u_url: "M3U playlist URL",
        hint_m3u: "The playlist link of your streaming provider. Stored in the server-side .env file (mode 0600), never in Git. Credentials inside the URL are masked in logs and status messages.",
        btn_show: "Show", btn_hide: "Hide", btn_delete: "Delete",
        lbl_tmdb_key: "TMDB API key (v3)", lbl_tmdb_bearer: "TMDB bearer token (v4)",
        hint_tmdb: "Either TMDB credential is enough for movie and series metadata. Create one at themoviedb.org → Settings → API.",
        lbl_meta_lang: "Metadata language",
        hint_meta_lang: "TMDB language code, e.g. de-DE, en-US, fr-FR.",
        btn_check_connection: "Check connection",
        checking_source: "Checking source …",
        check_ok: "Check succeeded.",
        check_done: "Check finished – see status.",
        check_failed: "Check failed.",
        btn_save: "Save changes",
        saved: "Saved. Changes take effect immediately.",
        save_failed: "Saving failed.",
        keep_placeholder: " – leave empty to keep",
        confirm_delete: "Really delete this value? It is removed on the server when saving.",
        deleted_placeholder: "Will be deleted on save",
        h_external_clients: "External clients",
        hint_api_key: "Scripts like the systemd refresh timer authenticate against protected endpoints with this key in the X-API-Key header.",
        apikey_status: "Status:",
        apikey_set: "set", apikey_not_set: "not set",
        btn_reveal: "Reveal", btn_regenerate: "Regenerate",
        confirm_regen: "Regenerate API key? Clients using the old key (e.g. the refresh timer) must be updated.",
        key_regenerated: "New API key created. The timer reads the .env file on each run; no manual update needed.",
        key_regen_failed: "Regeneration failed.",
        h_change_password: "Change admin password",
        lbl_current_pw: "Current password",
        lbl_new_pw: "New password (at least 8 characters)",
        lbl_new_pw2: "Repeat new password",
        btn_change_password: "Change password",
        err_pw_mismatch_new: "The new passwords do not match.",
        password_changed: "Password changed.",
        password_failed: "Password change failed.",
        language_heading: "Display",
        language_label: "Interface language",
        language_hint: "Applies to this browser immediately.",
      },
      de: {
        nav_library: "Bibliothek", nav_movies: "Filme", nav_series: "Serien", nav_live: "Live TV",
        nav_favorites: "Favoriten", nav_watched: "Gesehen", nav_settings: "Einstellungen",
        sub_library: "Deine Filme und Serien. Alles an einem Ort.",
        library_word: "Bibliothek",
        stat_entries: "Einträge", stat_new: "Neu", stat_popular: "Beliebt", stat_trending: "Trends",
        aria_main_nav: "Hauptnavigation",
        stat_upcoming: "Demnächst", stat_favorites: "Favoriten", stat_continue: "Weiterschauen",
        search_placeholder: "Titel oder Gruppe suchen …",
        filter_type: "Typ", filter_group: "Gruppe", filter_sort: "Sortierung",
        filter_language: "Sprache", all_languages: "Alle Sprachen",
        lang_de: "Deutsch", lang_multi: "Multi", lang_en: "Englisch", only_uhd: "4K",
        all_types: "Alle Typen", kind_movies: "Filme", kind_series: "Serien", kind_live: "Live",
        all_groups: "Alle Gruppen",
        sort_added: "Neu hinzugefügt", sort_title: "Titel A–Z", sort_rating: "Bewertung", sort_release: "Erscheinungsjahr",
        btn_update: "Update", btn_load_more: "Mehr laden", btn_open: "Öffnen", btn_open_tmdb: "Auf TMDB ansehen", btn_load_now: "Jetzt laden",
        badge_new: "NEU", label_movie: "Film", label_series: "Serie", label_live: "Live", label_tmdb: "TMDB",
        watched_label: "Gesehen",
        ver_count: "{n} Versionen",
        version_pick_title: "Version wählen",
        btn_close: "Schließen",
        favorites_toggle: "Favorit umschalten",
        reset_continue: "Aus Weiterschauen entfernen (setzt Gesehen-Fortschritt zurück)",
        episodes: "{n} Folgen", episodes_progress: "{w} / {t} Folgen gesehen",
        episodes_w_of_t: "{w} / {t} Folgen",
        col_number: "Nummer", col_title: "Titel", col_watched: "Gesehen", col_actions: "Aktionen",
        seasons: "Staffeln",
        mark_episode_watched: "Folge als gesehen markieren",
        poster_alt: "Poster von {title}",
        fallback_series: "SERIE", fallback_movie: "FILM", fallback_live: "LIVE", fallback_title: "TITEL",
        empty_all: "Keine Einträge. Nach dem Einrichten der M3U-Quelle auf «Update» klicken.",
        empty_trending: "Aktuell keine Trends aus TMDB in deiner Bibliothek.",
        empty_popular: "Aktuell keine beliebten Titel aus TMDB in deiner Bibliothek.",
        empty_upcoming: "Aktuell keine anstehenden Filme aus TMDB.",
        empty_continue: "Nichts angefangen – beginne eine Serie, dann erscheint sie hier.",
        empty_section: "Nichts in «{title}» markiert.",
        status_loading: "Bibliothek wird geladen …",
        status_shown: "{shown} von {matched} angezeigt",
        meta_error: "Fehler beim Laden der Metadaten: {msg}",
        meta_running: "Metadaten werden im Hintergrund geladen: {c} / {t}",
        meta_ready: "Metadaten sind bereit.",
        refresh_running: "Bibliothek wird neu geladen …",
        refresh_done: "Aktualisierung abgeschlossen – Bibliothek ist auf dem neuesten Stand.",
        update_available: "Aktualisierung verfügbar – die Bibliothek konnte nicht automatisch nachgeladen werden.",
        source_check_title: "Quelle in den Einstellungen prüfen",
        src_not_configured: "M3U-Quelle nicht konfiguriert",
        src_unknown: "Quelle noch nicht geprüft",
        src_checking: "Quelle wird geprüft …",
        src_ok: "Quelle erreichbar",
        src_auth_failed: "Anmeldung an der Quelle fehlgeschlagen",
        src_unreachable: "Quelle nicht erreichbar",
        src_invalid: "Keine gültige M3U-Playlist",
        src_empty: "Playlist ohne Einträge",
        entries_in_playlist: "Playlist gültig · {n} Einträge",
        entries_count: "{n} Einträge",
        last_check: "Letzte Prüfung: {age}",
        age_now: "vor weniger als 1 Min. geprüft",
        age_minutes: "vor {n} Min. geprüft",
        age_hours: "vor {n} Std. geprüft",
        age_days: "vor {n} Tagen geprüft",
        err_update_failed: "Aktualisierung fehlgeschlagen",
        err_login_required: "Anmeldung erforderlich – bitte in den Einstellungen anmelden und erneut versuchen.",
        err_load_failed: "Laden fehlgeschlagen",
        err_metadata_status: "Metadaten-Status fehlgeschlagen",
        err_series_load: "Serie konnte nicht geladen werden",
        btn_next_episode: "Nächste Folge öffnen", btn_all_watched: "Alle Folgen gesehen", btn_no_episode: "Keine Folge verfügbar",
        btn_favorite: "Favorit", btn_favorited: "Favorisiert",
        settings_title: "Einstellungen",
        back_to_library: "← Zur Bibliothek",
        btn_logout: "Abmelden",
        auth_title_setup: "Ersteinrichtung – Admin-Passwort wählen",
        auth_title_login: "Admin-Anmeldung",
        lbl_password: "Passwort", lbl_password2: "Passwort wiederholen",
        auth_hint_setup: "Dieses Passwort schützt die Einstellungen und alle Admin-Aktionen. Es wird serverseitig als bcrypt-Hash gespeichert.",
        btn_login: "Anmelden", btn_create_password: "Passwort erstellen",
        err_pw_mismatch: "Die Passwörter stimmen nicht überein.",
        err_setup_failed: "Einrichtung fehlgeschlagen.",
        msg_password_created: "Passwort erstellt.",
        err_login_failed: "Anmeldung fehlgeschlagen.",
        msg_logged_in: "Angemeldet.",
        tab_library: "Bibliothek", tab_access: "Zugriff", tab_security: "Sicherheit",
        h_source_metadata: "Quelle & Metadaten",
        lbl_m3u_url: "M3U-Playlist-URL",
        hint_m3u: "Der Playlist-Link deines Streaming-Anbieters. Gespeichert in der serverseitigen .env-Datei (Modus 0600), niemals in Git. Zugangsdaten in der URL werden in Logs und Statusmeldungen maskiert.",
        btn_show: "Anzeigen", btn_hide: "Ausblenden", btn_delete: "Löschen",
        lbl_tmdb_key: "TMDB-API-Schlüssel (v3)", lbl_tmdb_bearer: "TMDB-Bearer-Token (v4)",
        hint_tmdb: "Einer der beiden TMDB-Zugänge genügt für Metadaten zu Filmen und Serien. Erstellbar auf themoviedb.org → Einstellungen → API.",
        lbl_meta_lang: "Sprache der Metadaten",
        hint_meta_lang: "TMDB-Sprachcode, z. B. de-DE, en-US, fr-FR.",
        btn_check_connection: "Verbindung prüfen",
        checking_source: "Quelle wird geprüft …",
        check_ok: "Prüfung erfolgreich.",
        check_done: "Prüfung abgeschlossen – siehe Status.",
        check_failed: "Prüfung fehlgeschlagen.",
        btn_save: "Änderungen speichern",
        saved: "Gespeichert. Die Änderungen wirken sofort.",
        save_failed: "Speichern fehlgeschlagen.",
        keep_placeholder: " – leer lassen zum Beibehalten",
        confirm_delete: "Wert wirklich löschen? Er wird beim Speichern auf dem Server entfernt.",
        deleted_placeholder: "Wird beim Speichern gelöscht",
        h_external_clients: "Externe Clients",
        hint_api_key: "Skripte wie der systemd-Aktualisierungs-Timer authentifizieren sich über diesen Schlüssel im X-API-Key-Header gegen geschützte Endpunkte.",
        apikey_status: "Status:",
        apikey_set: "gesetzt", apikey_not_set: "nicht gesetzt",
        btn_reveal: "Anzeigen", btn_regenerate: "Neu generieren",
        confirm_regen: "API-Schlüssel neu generieren? Clients mit dem alten Schlüssel (z. B. der Aktualisierungs-Timer) müssen angepasst werden.",
        key_regenerated: "Neuer API-Schlüssel erstellt. Der Timer liest die .env-Datei bei jedem Lauf, kein manuelles Update nötig.",
        key_regen_failed: "Neugenerierung fehlgeschlagen.",
        h_change_password: "Admin-Passwort ändern",
        lbl_current_pw: "Aktuelles Passwort",
        lbl_new_pw: "Neues Passwort (mindestens 8 Zeichen)",
        lbl_new_pw2: "Neues Passwort wiederholen",
        btn_change_password: "Passwort ändern",
        err_pw_mismatch_new: "Die neuen Passwörter stimmen nicht überein.",
        password_changed: "Passwort geändert.",
        password_failed: "Passwortänderung fehlgeschlagen.",
        language_heading: "Anzeige",
        language_label: "Sprache der Oberfläche",
        language_hint: "Gilt sofort in diesem Browser.",
      },
    };
    const LANG = (() => { try { return localStorage.getItem("m3u-lang") === "de" ? "de" : "en"; } catch { return "en"; } })();
    const LOCALE = LANG === "de" ? "de-CH" : "en-US";
    function t(key, vars) {
      const table = I18N[LANG] || I18N.en;
      let s = table[key] != null ? table[key] : (I18N.en[key] != null ? I18N.en[key] : key);
      if (vars) for (const k of Object.keys(vars)) s = s.split("{" + k + "}").join(String(vars[k]));
      return s;
    }
    function applyStaticI18n() {
      document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
      document.querySelectorAll("[data-i18n-ph]").forEach((el) => { el.setAttribute("placeholder", t(el.dataset.i18nPh)); });
      document.querySelectorAll("[data-i18n-aria]").forEach((el) => { el.setAttribute("aria-label", t(el.dataset.i18nAria)); });
      document.documentElement.lang = LANG;
    }
"""

LIBRARY_HTML = r"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>M3U Library</title>
  <style>
    :root {
      --bg: #12161b;
      --bg-2: #171d24;
      --panel: #1b222a;
      --panel-2: #232b34;
      --line: #2c3641;
      --text: #e9eef4;
      --muted: #8fa0ae;
      --accent: #2dd4bf;
      --accent-strong: #22b3a2;
      --accent-soft: rgba(45, 212, 191, 0.12);
      --success: #34d399;
      --error: #f87171;
      --warning: #fbbf24;
      --radius: 10px;
      --sidebar-w: 232px;
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; padding: 0; }
    body {
      font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      font-size: 15px;
      line-height: 1.45;
    }
    *:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
    button, input, select, .button {
      font: inherit;
      color: var(--text);
      background: var(--panel-2);
      border: 1px solid var(--line);
      border-radius: var(--radius);
    }
    button { cursor: pointer; }
    button:hover, .button:hover { border-color: var(--accent); }
    button:disabled { opacity: 0.55; cursor: not-allowed; }
    .button {
      display: inline-flex; align-items: center; justify-content: center;
      gap: 8px; text-decoration: none; padding: 8px 14px; min-height: 38px;
    }
    .primary {
      background: var(--accent); border-color: var(--accent);
      color: #0b2b27; font-weight: 700;
    }
    .primary:hover { background: var(--accent-strong); border-color: var(--accent-strong); }
    .ghost { background: transparent; }

    /* Moderner Update-Button im Topbar */
    .refresh-btn {
      display: inline-flex; align-items: center; gap: 8px;
      padding: 9px 18px; border-radius: 999px;
      background: linear-gradient(135deg, rgba(45, 212, 191, 0.2), rgba(45, 212, 191, 0.08));
      border: 1px solid rgba(45, 212, 191, 0.45);
      color: var(--accent); font-weight: 700; font-size: 13.5px;
      letter-spacing: 0.02em; cursor: pointer;
      transition: background 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
    }
    .refresh-btn:hover:not(:disabled) {
      background: linear-gradient(135deg, rgba(45, 212, 191, 0.32), rgba(45, 212, 191, 0.14));
      border-color: var(--accent);
      box-shadow: 0 4px 20px rgba(45, 212, 191, 0.22);
      transform: translateY(-1px);
    }
    .refresh-btn:disabled { opacity: 0.6; cursor: not-allowed; }
    .refresh-btn:disabled svg { animation: refresh-spin 1s linear infinite; }
    @keyframes refresh-spin { to { transform: rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) {
      .refresh-btn, .refresh-btn:hover:not(:disabled) { transition: none; transform: none; }
      .refresh-btn:disabled svg { animation: none; }
    }
    .icon-btn {
      width: 34px; height: 34px; min-width: 34px; padding: 0;
      display: inline-flex; align-items: center; justify-content: center;
    }
    svg { display: block; }

    /* ---- App shell ---------------------------------------------------- */
    .app { display: grid; grid-template-columns: var(--sidebar-w) minmax(0, 1fr); min-height: 100vh; }
    .sidebar {
      position: sticky; top: 0; height: 100vh;
      background: var(--bg-2); border-right: 1px solid var(--line);
      display: flex; flex-direction: column; padding: 18px 12px;
      gap: 4px;
    }
    .brand {
      display: flex; align-items: center; gap: 10px;
      font-weight: 800; font-size: 18px; letter-spacing: 0.01em;
      padding: 6px 10px 18px; color: var(--accent);
    }
    .brand svg { color: var(--accent); }
    .nav { display: flex; flex-direction: column; gap: 2px; }
    .nav-item {
      display: flex; align-items: center; gap: 12px;
      padding: 9px 12px; border-radius: var(--radius);
      background: transparent; border: 1px solid transparent;
      color: var(--muted); text-decoration: none; text-align: left; width: 100%;
      font-size: 14.5px;
    }
    .nav-item:hover { color: var(--text); background: var(--panel); }
    .nav-item[aria-current="page"] {
      color: var(--accent); background: var(--accent-soft);
      border-color: rgba(45, 212, 191, 0.35); font-weight: 600;
    }
    .nav-item .count {
      margin-left: auto; font-size: 12px; color: var(--muted);
      background: var(--panel-2); border-radius: 99px; padding: 1px 8px;
    }
    .nav-item[aria-current="page"] .count { color: var(--accent); }
    .sidebar-footer { margin-top: auto; }

    .main { min-width: 0; padding: 22px 26px 48px; }

    /* ---- Topbar ------------------------------------------------------- */
    .topbar {
      display: flex; align-items: flex-start; gap: 16px; flex-wrap: wrap;
      margin-bottom: 16px;
    }
    .topbar h1 { margin: 0; font-size: 24px; line-height: 1.15; }
    .subtitle { margin: 3px 0 0; color: var(--muted); font-size: 13.5px; }
    .topbar-actions { margin-left: auto; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

    .source-chips { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; justify-content: flex-end; }
    @media (max-width: 700px) {
      .source-chips { flex-basis: 100%; order: 2; justify-content: flex-start; }
    }
    .chip {
      display: inline-flex; align-items: center; gap: 6px;
      border: 1px solid var(--line); background: var(--panel);
      color: var(--muted); border-radius: 99px; padding: 4px 11px; font-size: 12.5px;
      max-width: min(520px, 46vw); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .chip .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
    .chip.ok { color: var(--success); border-color: rgba(52, 211, 153, 0.4); }
    .chip.ok .dot { background: var(--success); }
    .chip.err { color: var(--error); border-color: rgba(248, 113, 113, 0.4); }
    .chip.err .dot { background: var(--error); }
    .chip.warn { color: var(--warning); border-color: rgba(251, 191, 36, 0.4); }
    .chip.warn .dot { background: var(--warning); }
    a.chip { text-decoration: none; }
    a.chip:hover { border-color: var(--accent); }

    /* Versions-Badges auf Filmkacheln (eigene Zeile unter Jahr/Typ) */
    .card-versions { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; margin-top: 5px; min-height: 0; }
    .ver-chips { display: contents; }
    .ver-chip {
      display: inline-flex; align-items: center; padding: 1px 7px; border-radius: 99px;
      border: 1px solid rgba(45, 212, 191, 0.35); color: var(--accent);
      font-size: 10.5px; font-weight: 700; letter-spacing: 0.04em; line-height: 1.6;
    }
    .ver-count { color: var(--muted); font-size: 11px; }

    /* Versions-Auswahl-Dialog */
    .modal-backdrop {
      position: fixed; inset: 0; z-index: 60; display: flex; align-items: center; justify-content: center;
      background: rgba(4, 10, 12, 0.72); backdrop-filter: blur(4px); padding: 20px;
    }
    .modal-backdrop[hidden] { display: none; }
    .modal {
      width: min(560px, 100%); max-height: 82vh; overflow: auto;
      background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius);
      box-shadow: 0 24px 80px rgba(0, 0, 0, 0.5);
    }
    .modal-head {
      display: flex; align-items: center; justify-content: space-between; gap: 12px;
      padding: 14px 18px; border-bottom: 1px solid var(--line);
      position: sticky; top: 0; background: var(--panel); z-index: 1;
    }
    .modal-head h2 { margin: 0; font-size: 17px; }
    .modal-close {
      border: 1px solid var(--line); background: var(--panel-2); color: var(--muted);
      width: 30px; height: 30px; min-width: 30px; border-radius: 8px; cursor: pointer;
      font-size: 16px; line-height: 1; display: grid; place-items: center;
    }
    .modal-close:hover { color: var(--text); border-color: var(--accent); }
    .modal-body { padding: 12px 14px 16px; display: grid; gap: 8px; }
    .ver-row {
      display: flex; align-items: center; gap: 10px; padding: 10px 12px;
      border: 1px solid var(--line); border-radius: 10px; background: var(--panel-2);
    }
    .ver-row:hover { border-color: var(--accent); }
    .ver-row .ver-tags { display: flex; gap: 4px; flex-wrap: wrap; min-width: 0; }
    .ver-row .ver-info { flex: 1; min-width: 0; }
    .ver-row .ver-title { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .ver-row .ver-group { color: var(--muted); font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .ver-row .button { flex-shrink: 0; }
    .ver-row .watched-mark { color: var(--success); flex-shrink: 0; display: inline-flex; }

    /* ---- Stats -------------------------------------------------------- */
    .stats { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
    .stat {
      border: 1px solid var(--line); background: var(--panel);
      border-radius: var(--radius); padding: 6px 12px;
      display: inline-flex; align-items: baseline; gap: 8px; font-size: 13px;
      color: var(--muted); cursor: pointer;
    }
    .stat:hover { border-color: var(--accent); }
    .stat .value { font-weight: 700; color: var(--text); font-size: 14.5px; }
    .stat.active { border-color: var(--accent); background: var(--accent-soft); color: var(--accent); }
    .stat.active .value { color: var(--accent); }

    /* ---- Filters ------------------------------------------------------ */
    .filters {
      display: grid; gap: 10px; margin-bottom: 14px;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    }
    .filters input, .filters select {
      width: 100%; min-height: 38px; padding: 6px 11px;
    }
    .filters input::placeholder { color: var(--muted); }
    .filters [hidden] { display: none; }
    .uhd-check {
      display: inline-flex; align-items: center; gap: 6px; min-height: 38px; padding: 6px 13px;
      border: 1px solid var(--line); border-radius: 8px; background: var(--panel);
      color: var(--muted); font-size: 13px; cursor: pointer; white-space: nowrap; user-select: none;
    }
    .uhd-check:hover { border-color: var(--accent); color: var(--text); }
    .uhd-check input { width: auto; min-height: 0; margin: 0; accent-color: var(--accent); cursor: pointer; }
    .sort-field { display: flex; flex-direction: column; gap: 3px; }
    .sort-field .field-label { font-size: 11px; color: var(--muted); letter-spacing: 0.04em; }

    .status-line { color: var(--muted); font-size: 13px; min-height: 20px; margin-bottom: 10px; }

    .update-banner {
      background: rgba(52, 211, 153, 0.1); border: 1px solid rgba(52, 211, 153, 0.4);
      color: var(--success); padding: 10px 14px; border-radius: var(--radius);
      margin-bottom: 12px; display: flex; gap: 12px; align-items: center; justify-content: space-between;
    }
    .update-banner[hidden] { display: none; }

    /* ---- Poster grid --------------------------------------------------- */
    .grid {
      display: grid; gap: 16px 14px;
      grid-template-columns: repeat(auto-fill, minmax(158px, 1fr));
    }
    .card { min-width: 0; }
    .poster-wrap {
      position: relative; aspect-ratio: 2 / 3; border-radius: var(--radius);
      overflow: hidden; background: var(--panel-2); border: 1px solid var(--line);
    }
    .poster-wrap img {
      width: 100%; height: 100%; object-fit: cover; display: block;
      /* Das Bild muss ueber dem absolut positionierten .poster-fallback
         liegen; ein statisches <img> wuerde sonst von dessen opaquem
         Hintergrund komplett uebermalt werden. */
      position: relative; z-index: 1;
      opacity: 0; transition: opacity 240ms ease;
    }
    .poster-wrap img.loaded { opacity: 1; }
    .poster-wrap:hover { border-color: var(--accent); }
    .poster-fallback {
      position: absolute; inset: 0; display: grid; place-items: center;
      color: var(--muted); font-size: 11px; font-weight: 700; letter-spacing: 0.12em;
      background: linear-gradient(160deg, var(--panel-2), var(--panel));
    }
    .poster-top {
      position: absolute; top: 0; left: 0; right: 0; padding: 6px;
      display: flex; justify-content: space-between; align-items: flex-start; gap: 6px;
      background: linear-gradient(180deg, rgba(10, 14, 17, 0.75), transparent);
      /* Muss ueber dem geladenen Poster liegen (img hat z-index 1). */
      z-index: 2;
    }
    .rating-badge {
      display: inline-flex; align-items: center; gap: 3px;
      background: rgba(10, 14, 17, 0.72); color: var(--warning);
      border-radius: 99px; padding: 2px 7px; font-size: 11.5px; font-weight: 700;
    }
    .fav-btn {
      width: 28px; height: 28px; min-width: 28px; border-radius: 50%;
      background: rgba(10, 14, 17, 0.72); border: none; color: rgba(255, 255, 255, 0.75);
      display: inline-flex; align-items: center; justify-content: center; padding: 0;
    }
    .fav-btn:hover { color: #fff; border: none; }
    .fav-btn.active { color: var(--accent); }
    .reset-btn {
      width: 28px; height: 28px; min-width: 28px; border-radius: 50%;
      background: rgba(10, 14, 17, 0.72); border: none; color: rgba(255, 255, 255, 0.75);
      display: inline-flex; align-items: center; justify-content: center; padding: 0;
    }
    .reset-btn:hover { color: #ff6b6b; border: none; }
    .poster-wrap img, .poster-wrap .poster-fallback { cursor: pointer; }
    .watched-badge {
      position: absolute; bottom: 8px; right: 8px;
      width: 26px; height: 26px; border-radius: 50%;
      background: rgba(10, 14, 17, 0.78); color: var(--success);
      display: grid; place-items: center; font-size: 13px;
    }
    .new-badge {
      position: absolute; bottom: 8px; left: 8px;
      background: var(--accent); color: #0b2b27;
      border-radius: 99px; padding: 2px 8px; font-size: 10.5px; font-weight: 800;
      letter-spacing: 0.05em;
    }
    .card-info { padding: 8px 2px 0; display: grid; gap: 3px; }
    .card-title {
      font-size: 13.5px; font-weight: 600; white-space: nowrap;
      overflow: hidden; text-overflow: ellipsis;
    }
    .card-meta { color: var(--muted); font-size: 12px; display: flex; gap: 6px; flex-wrap: wrap; }
    .progress { height: 4px; border-radius: 99px; background: var(--panel-2); overflow: hidden; margin-top: 5px; }
    .progress > span { display: block; height: 100%; background: var(--accent); border-radius: 99px; }
    .ep-count { color: var(--muted); font-size: 11.5px; margin-top: 3px; }
    .card-actions-row { display: flex; gap: 6px; margin-top: 7px; }
    .card-actions-row .button { flex: 1; min-height: 30px; padding: 3px 8px; font-size: 12px; }

    .empty {
      color: var(--muted); padding: 40px 0; text-align: center;
      border: 1px dashed var(--line); border-radius: var(--radius);
    }
    .load-more-wrap { display: flex; justify-content: center; margin-top: 22px; }

    /* ---- Series detail ------------------------------------------------- */
    #seriesView[hidden] { display: none; }
    .crumbs { margin-bottom: 14px; }
    .crumbs a { color: var(--muted); text-decoration: none; font-size: 13.5px; }
    .crumbs a:hover { color: var(--accent); }
    .series-hero {
      position: relative; border-radius: var(--radius); overflow: hidden;
      border: 1px solid var(--line); margin-bottom: 18px;
      background: var(--panel);
    }
    .series-backdrop {
      position: absolute; inset: -20px;
      background-size: cover; background-position: center 20%;
      filter: blur(28px) brightness(0.32) saturate(1.1);
    }
    .series-hero-inner {
      position: relative; display: grid; gap: 18px; padding: 20px;
      grid-template-columns: 150px minmax(0, 1fr); align-items: start;
    }
    .series-poster {
      aspect-ratio: 2 / 3; border-radius: var(--radius); overflow: hidden;
      border: 1px solid var(--line); background: var(--panel-2);
    }
    .series-poster img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .series-info { display: grid; gap: 10px; align-content: start; }
    .series-info h2 { margin: 0; font-size: 24px; }
    .series-meta { color: var(--muted); font-size: 13.5px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .series-desc { color: var(--text); font-size: 14px; max-width: 70ch; opacity: 0.92; }
    .series-actions { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
    .series-progress-row { display: grid; gap: 5px; max-width: 420px; }
    .series-progress-row .labels { display: flex; justify-content: space-between; color: var(--muted); font-size: 12px; }

    .season-tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
    .season-tab {
      border-radius: 99px; padding: 6px 14px; font-size: 13px; color: var(--muted);
      background: var(--panel); border: 1px solid var(--line);
    }
    .season-tab[aria-selected="true"] { color: var(--accent); border-color: var(--accent); background: var(--accent-soft); }

    .episode-table { width: 100%; border-collapse: collapse; }
    .episode-table th, .episode-table td {
      text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--line); font-size: 13.5px;
    }
    .episode-table th { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; }
    .episode-table td:last-child, .episode-table th:last-child { text-align: right; }
    .ep-num { color: var(--muted); white-space: nowrap; }
    .ep-title { min-width: 0; }
    .ep-toggle {
      width: 26px; height: 26px; min-width: 26px; border-radius: 50%; padding: 0;
      display: inline-flex; align-items: center; justify-content: center;
      color: var(--muted);
    }
    .ep-toggle.active { color: var(--success); border-color: var(--success); }
    .ep-open { min-height: 30px; padding: 3px 12px; font-size: 12.5px; }

    /* ---- Responsive ---------------------------------------------------- */
    @media (max-width: 900px) {
      .app { grid-template-columns: 1fr; }
      .sidebar {
        position: static; height: auto; flex-direction: row; align-items: center;
        overflow-x: auto; border-right: none; border-bottom: 1px solid var(--line);
        padding: 10px 12px; gap: 8px;
      }
      .brand { padding: 0 10px 0 0; }
      .nav { flex-direction: row; }
      .nav-item { width: auto; white-space: nowrap; padding: 7px 10px; }
      .nav-item .count { display: none; }
      .sidebar-footer { margin-top: 0; margin-left: auto; }
      .main { padding: 16px 14px 40px; }
      .filters { grid-template-columns: 1fr 1fr; }
      .filters input[type="search"] { grid-column: 1 / -1; }
      .series-hero-inner { grid-template-columns: 110px minmax(0, 1fr); padding: 14px; }
    }
    @media (max-width: 520px) {
      .filters { grid-template-columns: 1fr; }
      .grid { grid-template-columns: repeat(auto-fill, minmax(128px, 1fr)); gap: 12px 10px; }
      .episode-table th:nth-child(1), .episode-table td:nth-child(1) { display: none; }
    }
    @media (prefers-reduced-motion: reduce) {
      * { transition: none !important; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <div class="brand">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M2 9h20"/><path d="M8 4v5"/></svg>
        M3U Library
      </div>
      <nav class="nav" aria-label="Hauptnavigation" data-i18n-aria="aria_main_nav">
        <button class="nav-item" data-nav-view='{"kind":"","section":"all"}' aria-current="page">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/></svg>
          <span data-i18n="nav_library">Bibliothek</span>
        </button>
        <button class="nav-item" data-nav-view='{"kind":"movie","section":"all"}'>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="2" width="20" height="20" rx="2"/><path d="M7 2v20M17 2v20M2 12h20M2 7h5M2 17h5M17 17h5M17 7h5"/></svg>
          <span data-i18n="nav_movies">Filme</span>
        </button>
        <button class="nav-item" data-nav-view='{"kind":"series","section":"all"}'>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="6" width="20" height="14" rx="2"/><path d="M8 2 12 6l-4 4"/><path d="M17 3h4v4"/></svg>
          <span data-i18n="nav_series">Serien</span>
        </button>
        <button class="nav-item" data-nav-view='{"kind":"live","section":"all"}'>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="m8 3 4 4 4-4"/></svg>
          <span data-i18n="nav_live">Live TV</span>
        </button>
        <button class="nav-item" data-nav-view='{"kind":"","section":"favorites"}'>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20.5C7 16.5 3 13.2 3 9.3 3 6.4 5.2 4 8 4c1.6 0 3.1.8 4 2 .9-1.2 2.4-2 4-2 2.8 0 5 2.4 5 5.3 0 3.9-4 7.2-9 11.2z"/></svg>
          <span data-i18n="nav_favorites">Favoriten</span> <span class="count" id="navCountFav">0</span>
        </button>
        <button class="nav-item" data-nav-view='{"kind":"","section":"watched"}'>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="m8.5 12.5 2.5 2.5 4.5-5.5"/></svg>
          <span data-i18n="nav_watched">Gesehen</span> <span class="count" id="navCountWatched">0</span>
        </button>
        <button class="nav-item" data-nav-view='{"kind":"series","section":"continue"}'>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/></svg>
          <span data-i18n="stat_continue">Weiterschauen</span> <span class="count" id="navCountContinue">0</span>
        </button>
      </nav>
      <div class="sidebar-footer">
        <a class="nav-item" href="/settings">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h0a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h0a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          <span data-i18n="nav_settings">Einstellungen</span>
        </a>
      </div>
    </aside>

    <main class="main">
      <!-- Library view -->
      <div id="libraryView">
        <div class="topbar">
          <div>
            <h1 id="viewTitle">Bibliothek</h1>
            <p class="subtitle" data-i18n="sub_library">Deine Filme und Serien. Alles an einem Ort.</p>
          </div>
          <div class="topbar-actions">
            <div class="source-chips" id="sourceChips" aria-live="polite"></div>
            <button class="refresh-btn" id="refreshBtn" type="button">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg>
              <span data-i18n="btn_update">Update</span>
            </button>
          </div>
        </div>

        <div class="stats" role="group" aria-label="Kennzahlen und Schnellfilter">
          <button class="stat" data-stat-section="all" type="button"><span class="value" id="statTotal">0</span> <span data-i18n="stat_entries">Einträge</span></button>
          <button class="stat" data-stat-section="new" type="button"><span class="value" id="statNew">0</span> <span data-i18n="stat_new">Neu</span></button>
          <button class="stat" data-stat-section="popular" type="button"><span class="value" id="statPopular">0</span> <span data-i18n="stat_popular">Beliebt</span></button>
          <button class="stat" data-stat-section="trending" type="button"><span class="value" id="statTrending">0</span> <span data-i18n="stat_trending">Trends</span></button>
          <button class="stat" data-stat-section="upcoming" type="button"><span class="value" id="statUpcoming">0</span> <span data-i18n="stat_upcoming">Demnächst</span></button>
          <button class="stat" data-stat-section="favorites" type="button"><span class="value" id="statFav">0</span> <span data-i18n="stat_favorites">Favoriten</span></button>
        </div>

        <div class="filters">
          <input type="search" id="search" placeholder="Titel oder Gruppe suchen …" data-i18n-ph="search_placeholder" aria-label="Titel oder Gruppe suchen" data-i18n-aria="search_placeholder">
          <select id="kind" aria-label="Typ" data-i18n-aria="filter_type">
            <option value="" data-i18n="all_types">Alle Typen</option>
            <option value="movie" data-i18n="kind_movies">Filme</option>
            <option value="series" data-i18n="kind_series">Serien</option>
            <option value="live" data-i18n="kind_live">Live</option>
          </select>
          <select id="lang" aria-label="Sprache" data-i18n-aria="filter_language" hidden>
            <option value="" data-i18n="all_languages">Alle Sprachen</option>
            <option value="de" data-i18n="lang_de">Deutsch</option>
            <option value="multi" data-i18n="lang_multi">Multi</option>
            <option value="en" data-i18n="lang_en">Englisch</option>
          </select>
          <label class="uhd-check" id="uhdWrap" hidden>
            <input type="checkbox" id="uhd">
            <span data-i18n="only_uhd">4K</span>
          </label>
          <select id="group" aria-label="Gruppe" data-i18n-aria="filter_group"><option value="" data-i18n="all_groups">Alle Gruppen</option></select>
          <div class="sort-field">
            <span class="field-label" data-i18n="filter_sort">Sortierung</span>
            <select id="sort" aria-label="Sortierung" data-i18n-aria="filter_sort">
              <option value="added" data-i18n="sort_added">Neu hinzugefügt</option>
              <option value="title" data-i18n="sort_title">Titel A–Z</option>
              <option value="rating" data-i18n="sort_rating">Bewertung</option>
              <option value="release" data-i18n="sort_release" selected>Erscheinungsjahr</option>
            </select>
          </div>
        </div>

        <div class="status-line" id="status" aria-live="polite"></div>
        <div class="update-banner" id="updateBanner" hidden>
          <span data-i18n="update_available">Aktualisierung verfügbar – die Bibliothek konnte nicht automatisch nachgeladen werden.</span>
          <button id="updateBannerAction" class="primary" type="button" data-i18n="btn_load_now">Jetzt laden</button>
        </div>

        <div id="library" class="empty" data-i18n="status_loading">Bibliothek wird geladen …</div>
        <div class="load-more-wrap"><button id="loadMore" class="ghost" type="button" hidden data-i18n="btn_load_more">Mehr laden</button></div>
      </div>

      <!-- Series detail view -->
      <div id="seriesView" hidden></div>
    </main>
  </div>

  <!-- Versions-Auswahl fuer Filme mit mehreren Qualitaets-/Sprachvarianten -->
  <div class="modal-backdrop" id="versionModal" hidden>
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="versionModalTitle">
      <div class="modal-head">
        <h2 id="versionModalTitle"></h2>
        <button type="button" class="modal-close" id="versionModalClose" aria-label="×">×</button>
      </div>
      <div class="modal-body" id="versionModalBody"></div>
    </div>
  </div>

  <script>
__I18N_INLINE__
  (async function () {
    "use strict";

    const els = {
      library: document.getElementById("library"),
      status: document.getElementById("status"),
      search: document.getElementById("search"),
      kind: document.getElementById("kind"),
      group: document.getElementById("group"),
      sort: document.getElementById("sort"),
      lang: document.getElementById("lang"),
      uhd: document.getElementById("uhd"),
      uhdWrap: document.getElementById("uhdWrap"),
      loadMore: document.getElementById("loadMore"),
      refresh: document.getElementById("refreshBtn"),
      statTotal: document.getElementById("statTotal"),
      statNew: document.getElementById("statNew"),
      statPopular: document.getElementById("statPopular"),
      statTrending: document.getElementById("statTrending"),
      statUpcoming: document.getElementById("statUpcoming"),
      statFav: document.getElementById("statFav"),
      navCountFav: document.getElementById("navCountFav"),
      navCountWatched: document.getElementById("navCountWatched"),
      navCountContinue: document.getElementById("navCountContinue"),
      libraryView: document.getElementById("libraryView"),
      seriesView: document.getElementById("seriesView"),
      sourceChips: document.getElementById("sourceChips"),
      viewTitle: document.getElementById("viewTitle"),
    };

    const pageParams = new URLSearchParams(location.search);
    const pathMatch = location.pathname.match(/^\/series\/([^/]+)/);
    const currentSeriesId = pathMatch ? decodeURIComponent(pathMatch[1]) : null;

    const state = {
      items: [],
      matched: 0,
      total: 0,
      groups: [],
      sectionCounts: { total: 0, new: 0, popular: 0, trending: 0, upcoming: 0, favorites: 0, watched: 0, continue: 0 },
      lastRefresh: null,
      metadataStatus: { running: false, total: 0, completed: 0, error: null },
      section: "all",
      newWindow: "refresh",
      limit: 60,
    };

    const SECTION_KEYS = {
      all: "nav_library", new: "stat_new", popular: "stat_popular", trending: "stat_trending",
      upcoming: "stat_upcoming", favorites: "nav_favorites", watched: "nav_watched",
      continue: "stat_continue",
    };
    const KIND_KEYS = { movie: "kind_movies", series: "kind_series", live: "nav_live" };

    let csrfToken = null;

    function esc(value) {
      return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
    }

    /* TMDB-Poster laufen ueber den serverseitigen Proxy (siehe /api/poster):
       same-origin, serverseitig gecacht, immun gegen Client-Rate-Limits,
       DNS/Ad-Blocking und Throttling in versteckten Tabs. Alle anderen
       Bild-URLs (z.B. Sender-Logos aus der M3U) werden direkt geladen. */
    function posterProxy(url) {
      if (typeof url === "string" && url.startsWith("https://image.tmdb.org/")) {
        return "/api/poster?u=" + encodeURIComponent(url);
      }
      return url;
    }

    function yearOf(dateStr) {
      const m = /^(\d{4})/.exec(String(dateStr || ""));
      return m ? m[1] : "";
    }

    function ratingOf(item) {
      const r = Number(item.rating);
      return Number.isFinite(r) && r > 0 ? r.toFixed(1) : null;
    }

    function formatCount(n) {
      return Number(n || 0).toLocaleString(LOCALE);
    }

    /* ---- Auth ------------------------------------------------------------ */
    async function refreshAuthStatus() {
      try {
        const res = await fetch("/api/auth/status", { cache: "no-store" });
        const data = await res.json();
        if (data.authenticated) csrfToken = data.csrf;
      } catch (error) {
        csrfToken = null;
      }
    }

    async function apiFetch(url, options = {}) {
      const method = (options.method || "GET").toUpperCase();
      const headers = Object.assign({}, options.headers || {});
      if (csrfToken && method !== "GET") headers["X-CSRF-Token"] = csrfToken;
      return fetch(url, { cache: "no-store", ...options, headers });
    }

    /* ---- Source status chips --------------------------------------------- */
    const SOURCE_LABEL_KEYS = {
      not_configured: "src_not_configured",
      unknown: "src_unknown",
      checking: "src_checking",
      ok: "src_ok",
      auth_failed: "src_auth_failed",
      unreachable: "src_unreachable",
      invalid: "src_invalid",
      empty: "src_empty",
    };

    function checkedAge(checkedAt) {
      if (!checkedAt) return "";
      const ms = Date.now() - new Date(checkedAt).getTime();
      if (!Number.isFinite(ms) || ms < 0) return "";
      const min = Math.floor(ms / 60000);
      if (min < 1) return t("age_now");
      if (min < 60) return t("age_minutes", { n: min });
      const h = Math.floor(min / 60);
      if (h < 24) return t("age_hours", { n: h });
      return t("age_days", { n: Math.floor(h / 24) });
    }

    async function loadSourceStatus() {
      try {
        const res = await fetch("/api/source-status", { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        renderSourceChips(data);
      } catch (error) {
        console.error(error);
      }
    }

    function renderSourceChips(data) {
      const chipClass = { ok: "ok", auth_failed: "err", unreachable: "err", invalid: "err", empty: "warn", unknown: "", not_configured: "warn", checking: "" }[data.state] || "";
      const parts = [t(SOURCE_LABEL_KEYS[data.state] || "src_unknown")];
      if (data.state === "ok" && data.entry_count != null) parts.push(t("entries_in_playlist", { n: formatCount(data.entry_count) }));
      if (data.state === "empty" && data.entry_count != null) parts.push(t("entries_count", { n: formatCount(data.entry_count) }));
      if (data.state === "ok" || data.state === "empty" || data.state === "invalid") {
        const age = checkedAge(data.checked_at);
        if (age) parts.push(age);
      } else if (data.checked_at && (data.state === "auth_failed" || data.state === "unreachable")) {
        const age = checkedAge(data.checked_at);
        if (age) parts.push(t("last_check", { age }));
      }
      els.sourceChips.innerHTML = `<a class="chip ${chipClass}" href="/settings" title="${esc(t("source_check_title"))}"><span class="dot" aria-hidden="true"></span>${esc(parts.join(" · "))}</a>`;
    }

    /* ---- Stats / nav ------------------------------------------------------ */
    function applyStats() {
      const c = state.sectionCounts;
      els.statTotal.textContent = formatCount(state.total || c.total || 0);
      els.statNew.textContent = formatCount(c.new || 0);
      els.statPopular.textContent = formatCount(c.popular || 0);
      els.statTrending.textContent = formatCount(c.trending || 0);
      els.statUpcoming.textContent = formatCount(c.upcoming || 0);
      els.statFav.textContent = formatCount(c.favorites || 0);
      els.navCountFav.textContent = formatCount(c.favorites || 0);
      els.navCountWatched.textContent = formatCount(c.watched || 0);
      els.navCountContinue.textContent = formatCount(c.continue || 0);
      document.querySelectorAll("[data-stat-section]").forEach((btn) => {
        btn.classList.toggle("active", btn.dataset.statSection === state.section);
      });
    }

    function syncNav() {
      const current = JSON.stringify({ kind: els.kind.value, section: state.section });
      document.querySelectorAll("[data-nav-view]").forEach((btn) => {
        if (JSON.stringify(JSON.parse(btn.dataset.navView)) === current) {
          btn.setAttribute("aria-current", "page");
        } else {
          btn.removeAttribute("aria-current");
        }
      });
    }

    function currentLibraryParams() {
      const params = new URLSearchParams();
      if (els.search.value.trim()) params.set("q", els.search.value.trim());
      if (els.kind.value) params.set("kind", els.kind.value);
      if (els.group.value) params.set("group", els.group.value);
      if (els.sort.value && els.sort.value !== "release") params.set("sort", els.sort.value);
      if (state.section && state.section !== "all") params.set("section", state.section);
      if (state.newWindow && state.newWindow !== "refresh") params.set("new_window", state.newWindow);
      if (versionFiltersActive()) {
        if (els.lang.value) params.set("lang", els.lang.value);
        if (els.uhd.checked) params.set("uhd", "1");
      }
      return params;
    }

    /* Sprach-/4K-Filter gelten fuer Filme und Serien. */
    function versionFiltersActive() {
      return els.kind.value === "movie" || els.kind.value === "series";
    }

    function syncVersionFilterVisibility() {
      const show = versionFiltersActive();
      els.lang.hidden = !show;
      els.uhdWrap.hidden = !show;
    }

    /* Auf der Serien-Detailseite fuehrt jeder Bibliotheks-View-Wechsel ueber eine
       echte Navigation: sonst bleibt die URL auf /series/<id> stehen und ein Reload
       oeffnet die Serie wieder, obwohl der Nutzer längst in der Bibliothek ist. */
    function libraryUrlFor(view) {
      const params = new URLSearchParams();
      if (view.kind) params.set("kind", view.kind);
      if (view.section && view.section !== "all") params.set("section", view.section);
      const query = params.toString();
      return query ? `/?${query}` : "/";
    }

    function syncLibraryUrl() {
      if (currentSeriesId) return;
      const query = currentLibraryParams().toString();
      history.replaceState(null, "", query ? `/?${query}` : "/");
    }

    function viewTitle() {
      if (state.section && state.section !== "all" && SECTION_KEYS[state.section]) return t(SECTION_KEYS[state.section]);
      if (els.kind.value && KIND_KEYS[els.kind.value]) return t(KIND_KEYS[els.kind.value]);
      return t(SECTION_KEYS[state.section] || "nav_library");
    }

    function updateTitle() {
      els.viewTitle.textContent = viewTitle();
      document.title = `${viewTitle()} · M3U Library`;
    }

    /* ---- Cache ------------------------------------------------------------ */
    const CACHE_KEY = "m3u-library-cache-v3";

    function loadCache() {
      try { return JSON.parse(localStorage.getItem(CACHE_KEY)) || null; } catch { return null; }
    }
    function saveCache(cacheState) {
      try { localStorage.setItem(CACHE_KEY, JSON.stringify(cacheState)); } catch {}
    }
    function clearCache() {
      try { localStorage.removeItem(CACHE_KEY); } catch {}
    }

    function showUpdateBanner() {
      const banner = document.getElementById("updateBanner");
      if (banner) banner.hidden = false;
    }
    function hideUpdateBanner() {
      const banner = document.getElementById("updateBanner");
      if (banner) banner.hidden = true;
    }

    /* ---- Metadata ---------------------------------------------------------- */
    function metadataStatusText() {
      if (state.metadataStatus.error) return t("meta_error", { msg: state.metadataStatus.error });
      if (state.metadataStatus.running) return t("meta_running", { c: state.metadataStatus.completed, t: state.metadataStatus.total });
      if (state.metadataStatus.total && state.metadataStatus.completed >= state.metadataStatus.total) return t("meta_ready");
      return "";
    }

    async function refreshMetadataStatus() {
      const res = await apiFetch("/api/metadata/status");
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Metadaten-Status fehlgeschlagen");
      state.metadataStatus = data;
      applyStats();
    }

    /* Auf der Serien-Detailseite laeuft kein load(): Zaehler einmalig
       nachladen, sonst zeigt die Sidebar ueberall 0 an. */
    async function refreshSectionCounts() {
      const res = await apiFetch("/api/items?limit=1");
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || t("err_load_failed"));
      if (data.section_counts) {
        state.sectionCounts = data.section_counts;
        applyStats();
      }
    }

    /* Tabs, die laenger offen bleiben, erkennen sonst keinen Refresh:
       Karten auf dem Bildschirm veralten, Klicks landen auf 404-IDs.
       Alle 5 s last_refresh pruefen und bei Aenderung automatisch nachladen. */
    let updateCheckInFlight = false;
    async function checkForLibraryUpdates() {
      if (updateCheckInFlight || currentSeriesId) return;
      if (!state.lastRefresh) return;
      updateCheckInFlight = true;
      try {
        const res = await apiFetch("/api/status");
        if (!res.ok) return;
        const data = await res.json();
        if (data.last_refresh && data.last_refresh !== state.lastRefresh) {
          hideUpdateBanner();
          await load(false);
        }
      } finally {
        updateCheckInFlight = false;
      }
    }

    async function enrichVisibleMetadata() {
      if (els.kind.value === "series") return;
      const ids = state.items
        .filter((item) => item.kind !== "live" && item.kind !== "series" && !item.metadata_title && !item.poster_url)
        .slice(0, 18)
        .map((item) => item.id);
      if (!ids.length) return;
      try {
        const res = await apiFetch("/api/metadata/enrich", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(ids),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || t("err_metadata_status"));
        const byId = Object.fromEntries((data.items || []).map((item) => [item.item_id, item]));
        let changed = false;
        state.items = state.items.map((item) => {
          const meta = byId[item.id];
          if (!meta) return item;
          changed = true;
          return { ...item, metadata_title: meta.title, release_date: meta.release_date, rating: meta.rating, description: meta.description, poster_url: meta.poster_url };
        });
        if (changed) renderLibrary();
      } catch (error) {
        console.error(error);
      }
    }

    function updateGroups(groups) {
      const current = els.group.value;
      state.groups = groups || [];
      els.group.innerHTML = `<option value="">${esc(t("all_groups"))}</option>` + state.groups.map((group) => `<option value="${esc(group)}">${esc(group)}</option>`).join("");
      els.group.value = state.groups.includes(current) ? current : "";
    }

    /* ---- Loading ----------------------------------------------------------- */
    async function load(append = false) {
      const isSeriesList = els.kind.value === "series";
      const params = new URLSearchParams({
        limit: String(state.limit),
        offset: append ? String(state.items.length) : "0",
        section: state.section,
        sort: els.sort.value,
        new_window: state.newWindow || "refresh",
      });
      if (els.search.value.trim()) params.set("q", els.search.value.trim());
      if (!isSeriesList && els.kind.value) params.set("kind", els.kind.value);
      if (els.group.value && !isSeriesList) params.set("group", els.group.value);
      if (versionFiltersActive()) {
        if (els.lang.value) params.set("lang", els.lang.value);
        if (els.uhd.checked) params.set("uhd", "1");
      }
      const endpoint = isSeriesList ? `/api/series?${params}` : `/api/items?${params}`;
      syncLibraryUrl();
      syncVersionFilterVisibility();
      els.status.textContent = append ? t("btn_load_more") + " …" : t("status_loading");
      const res = await apiFetch(endpoint);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || t("err_load_failed"));
      state.items = append ? state.items.concat(data.items) : data.items;
      state.matched = data.matched;
      state.total = data.total;
      state.groups = data.groups || [];
      state.sectionCounts = data.section_counts || state.sectionCounts;
      state.lastRefresh = data.last_refresh;
      state.metadataStatus = data.metadata_status || state.metadataStatus;
      if (!isSeriesList) updateGroups(state.groups);
      renderLibrary();
      enrichVisibleMetadata();
      saveCache({
        lastRefresh: state.lastRefresh,
        items: state.items,
        matched: state.matched,
        total: state.total,
        groups: state.groups,
        sectionCounts: state.sectionCounts,
        kind: els.kind.value,
        section: state.section,
        sort: els.sort.value,
        search: els.search.value || "",
        group: els.group.value || "",
        newWindow: state.newWindow,
        lang: els.lang.value,
        uhd: els.uhd.checked ? "1" : "",
      });
    }

    async function refreshSectionCountsOnly() {
      if (!currentSeriesId) return;
      const isSeriesList = els.kind.value === "series";
      const params = new URLSearchParams({
        limit: "1", offset: "0", section: state.section, sort: els.sort.value,
        new_window: state.newWindow || "refresh",
      });
      if (els.search.value.trim()) params.set("q", els.search.value.trim());
      if (!isSeriesList && els.kind.value) params.set("kind", els.kind.value);
      if (els.group.value && !isSeriesList) params.set("group", els.group.value);
      if (versionFiltersActive()) {
        if (els.lang.value) params.set("lang", els.lang.value);
        if (els.uhd.checked) params.set("uhd", "1");
      }
      const endpoint = isSeriesList ? `/api/series?${params}` : `/api/items?${params}`;
      const res = await apiFetch(endpoint);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || t("err_update_failed"));
      state.sectionCounts = data.section_counts || state.sectionCounts;
      state.lastRefresh = data.last_refresh || state.lastRefresh;
      applyStats();
    }

    /* ---- Cards ------------------------------------------------------------- */
    const KIND_LABELS = { movie: t("label_movie"), series: t("label_series"), live: t("label_live") };

    function posterHtml(item) {
      const url = item.poster_url || item.logo;
      const fallback = `<div class="poster-fallback" aria-hidden="true">${esc((KIND_LABELS[item.kind] || t("fallback_title")).toUpperCase())}</div>`;
      if (!url) return fallback;
      return `${fallback}<img data-src="${esc(posterProxy(url))}" alt="" decoding="async" onload="this.classList.add('loaded')">`;
    }

    function favoriteButton(item) {
      const active = item.is_favorite ? " active" : "";
      const attr = item.kind === "series" ? `data-series-favorite="${esc(item.id)}"` : `data-favorite="${esc(item.id)}"`;
      return `<button type="button" class="fav-btn${active}" ${attr} aria-label="${esc(t("favorites_toggle"))}" aria-pressed="${!!item.is_favorite}" title="${esc(t("favorites_toggle"))}"><svg width="14" height="14" viewBox="0 0 24 24" fill="${item.is_favorite ? "currentColor" : "none"}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20.5C7 16.5 3 13.2 3 9.3 3 6.4 5.2 4 8 4c1.6 0 3.1.8 4 2 .9-1.2 2.4-2 4-2 2.8 0 5 2.4 5 5.3 0 3.9-4 7.2-9 11.2z"/></svg></button>`;
    }

    /* In Weiterschauen: Serie aus der Liste entfernen (setzt den Watch-Fortschritt zurück). */
    function resetButton(item) {
      if (item.kind !== "series" || state.section !== "continue") return "";
      return `<button type="button" class="reset-btn" data-series-reset="${esc(item.id)}" aria-label="${esc(t("reset_continue"))}" title="${esc(t("reset_continue"))}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg></button>`;
    }

    function cardHtml(item) {
      const rating = ratingOf(item);
      const year = yearOf(item.release_date);
      const isExternal = !!item.is_external;
      const typeLabel = isExternal ? t("label_tmdb") : (KIND_LABELS[item.kind] || item.kind);
      let progressHtml = "";
      let statusBadge = "";
      if (item.kind === "series" && item.episode_count) {
        const watched = item.watched_episode_count || 0;
        const total = item.episode_count;
        const pct = Math.min(100, Math.round((watched / total) * 100));
        progressHtml = `<div class="progress" role="progressbar" aria-valuenow="${watched}" aria-valuemin="0" aria-valuemax="${total}"><span style="width:${pct}%"></span></div><div class="ep-count">${esc(t("episodes_w_of_t", { w: watched, t: total }))}</div>`;
      } else if (item.kind !== "series") {
        if (item.is_watched) {
          statusBadge = `<span class="watched-badge" title="${esc(t("watched_label"))}"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m4.5 12.5 5 5 10-11"/></svg></span>`;
        }
        if (item.is_new) {
          statusBadge += `<span class="new-badge">${esc(t("badge_new"))}</span>`;
        }
      }
      const versions = Array.isArray(item.versions) ? item.versions : [];
      const verCount = item.version_count || versions.length || 1;
      const verTags = item.kind === "movie" ? [...new Set(versions.flatMap((v) => v.tags || []))] : [];
      const verChips = verTags.length
        ? `<span class="ver-chips">${verTags.map((tag) => `<span class="ver-chip">${esc(tag)}</span>`).join("")}${verCount > 1 ? `<span class="ver-count">${esc(t("ver_count", { n: verCount }))}</span>` : ""}</span>`
        : "";
      const openAction = isExternal
        ? `<a class="button ghost ep-open" href="${esc(item.provider_url || "#")}" target="_blank" rel="noreferrer">${esc(t("btn_open_tmdb"))}</a>`
        : (item.kind === "series" || item.episode_count != null)
          ? `<a class="button ghost ep-open" href="/series/${encodeURIComponent(item.id)}${currentLibraryParams().toString() ? `?${currentLibraryParams().toString()}` : ""}">${esc(t("btn_open"))}</a>`
          : verCount > 1
            ? `<button type="button" class="button ghost ep-open" data-version-picker="${esc(item.id)}">${esc(t("btn_open"))}</button>`
            : `<a class="button ghost ep-open" href="/watch/${encodeURIComponent(item.id)}.m3u">${esc(t("btn_open"))}</a>`;
      return `
        <article class="card" data-card="${esc(item.id)}" data-item-id="${esc(item.id)}">
          <div class="poster-wrap">
            ${posterHtml(item)}
            <div class="poster-top">
              ${rating ? `<span class="rating-badge"><svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4 6.1 20.5l1.2-6.5L2.5 9.4l6.6-.9z"/></svg>${esc(rating)}</span>` : "<span></span>"}
              ${favoriteButton(item)}
              ${resetButton(item)}
            </div>
            ${statusBadge}
          </div>
          <div class="card-info">
            <div class="card-title" title="${esc(item.title)}">${esc(item.title)}</div>
            <div class="card-meta">${year ? `<span>${esc(year)}</span>` : ""}<span>${esc(typeLabel)}</span>${item.kind === "series" && item.episode_count > 0 && item.watched_episode_count >= item.episode_count ? `<span>${esc(t("watched_label"))}</span>` : ""}</div>
            ${verChips ? `<div class="card-versions">${verChips}</div>` : ""}
            ${progressHtml}
            <div class="card-actions-row">${openAction}</div>
          </div>
        </article>`;
    }

    function normalizeHtml(html) {
      return html
        .replace(/\s(?:src|data-src|data-retries)="[^"]*"/g, ' src="')
        .replace(/\sclass="([^"]*)"/g, (_m, cls) => {
          const kept = cls.split(/\s+/).filter((c) => c && c !== "loaded");
          return kept.length ? ` class="${kept.join(" ")}"` : "";
        })
        .replace(/\s+/g, " ")
        .replace(/>\s+</g, "><")
        .trim();
    }

    /* Eigenes Lazy-Loading: Chrome triggert loading="lazy" auf per JS
       eingefuegten Grid-Bildern zuverlaessig nicht (Requests starten nie).
       IO als Hauptmechanismus + direkte Sichtbarkeitspruefung als Fallback,
       damit es auch in versteckten/entfokussierten Tabs funktioniert. */
    const posterObserver = ("IntersectionObserver" in window)
      ? new IntersectionObserver((entries) => {
          for (const entry of entries) {
            if (!entry.isIntersecting) continue;
            revealPoster(entry.target);
          }
        }, { rootMargin: "400px" })
      : null;

    function revealPoster(img) {
      if (img.dataset.src) { img.src = img.dataset.src; delete img.dataset.src; }
      if (posterObserver) posterObserver.unobserve(img);
    }

    function revealVisiblePosters(root) {
      const vh = window.innerHeight || document.documentElement.clientHeight || 0;
      for (const img of root.querySelectorAll("img[data-src]")) {
        const r = img.getBoundingClientRect();
        if (r.top < vh + 400 && r.bottom > -400) revealPoster(img);
      }
    }

    function observePosters(root) {
      const imgs = root.querySelectorAll("img[data-src]");
      if (posterObserver) {
        for (const img of imgs) posterObserver.observe(img);
      }
      revealVisiblePosters(root);
    }

    let posterRevealTick = false;
    function queuePosterReveal() {
      if (posterRevealTick) return;
      posterRevealTick = true;
      setTimeout(() => {
        posterRevealTick = false;
        revealVisiblePosters(document);
      }, 150);
    }
    window.addEventListener("scroll", queuePosterReveal, { passive: true });
    window.addEventListener("resize", queuePosterReveal);
    document.addEventListener("visibilitychange", queuePosterReveal);

    /* Fehlgeschlagene Ladevorgaenge (z.B. durch Rebuilds abgebrochene
       Requests) begrenzt wiederholen; erst danach Fallback anzeigen. */
    function handlePosterError(event) {
      const img = event.target;
      if (!(img instanceof HTMLImageElement) || !img.closest(".poster-wrap")) return;
      const retries = (+img.dataset.retries || 0) + 1;
      img.dataset.retries = String(retries);
      img.classList.remove("loaded");
      if (retries >= 3 || !img.getAttribute("src")) {
        img.remove();
        return;
      }
      const src = img.getAttribute("src");
      img.removeAttribute("src");
      setTimeout(() => {
        if (!img.isConnected) return;
        img.dataset.src = src;
        revealPoster(img);
      }, 600 * retries);
    }
    document.addEventListener("error", handlePosterError, true);

    function renderLibrary() {
      updateTitle(); syncNav(); applyStats();
      const metaText = metadataStatusText();
      els.status.textContent = metaText || t("status_shown", { shown: state.items.length, matched: formatCount(state.matched) });
      els.loadMore.hidden = state.items.length >= state.matched;
      if (!state.items.length) {
        const emptyBySection = {
          all: t("empty_all"),
          trending: t("empty_trending"),
          popular: t("empty_popular"),
          upcoming: t("empty_upcoming"),
          continue: t("empty_continue"),
        };
        els.library.className = "empty";
        els.library.textContent = emptyBySection[state.section] || t("empty_section", { title: viewTitle() });
        return;
      }
      els.library.className = "grid";
      const existing = new Map();
      for (const card of els.library.querySelectorAll("[data-item-id]")) {
        existing.set(card.dataset.itemId, card);
      }
      const fragment = document.createDocumentFragment();
      for (const item of state.items) {
        const html = cardHtml(item);
        const old = existing.get(item.id);
        if (old && normalizeHtml(old.outerHTML) === normalizeHtml(html)) {
          fragment.appendChild(old);
        } else {
          const wrapper = document.createElement("div");
          wrapper.innerHTML = html.trim();
          fragment.appendChild(wrapper.firstElementChild);
        }
      }
      els.library.innerHTML = "";
      els.library.appendChild(fragment);
      observePosters(els.library);
    }

    /* ---- Version picker (movies with several language/quality variants) --- */
    function openVersionPicker(id) {
      const item = state.items.find((i) => i.id === id);
      if (!item || !Array.isArray(item.versions) || !item.versions.length) return;
      const modal = document.getElementById("versionModal");
      document.getElementById("versionModalTitle").textContent = item.title;
      document.getElementById("versionModalBody").innerHTML = item.versions.map((v) => `
        <div class="ver-row">
          <span class="ver-tags">${(v.tags || []).map((tag) => `<span class="ver-chip">${esc(tag)}</span>`).join("")}</span>
          <span class="ver-info">
            <span class="ver-title" title="${esc(v.title)}">${esc(v.title)}</span>
            <span class="ver-group">${esc(v.group_name || "")}</span>
          </span>
          ${v.is_watched ? `<span class="watched-mark" title="${esc(t("watched_label"))}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m4.5 12.5 5 5 10-11"/></svg></span>` : ""}
          <a class="button primary" href="/watch/${encodeURIComponent(v.id)}.m3u">${esc(t("btn_open"))}</a>
        </div>`).join("");
      modal.hidden = false;
    }

    function closeVersionPicker() {
      const modal = document.getElementById("versionModal");
      if (modal) modal.hidden = true;
    }

    /* ---- Toggles ------------------------------------------------------------ */
    async function toggleItem(id, mode) {
      const res = await apiFetch(`/api/items/${encodeURIComponent(id)}/${mode}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || t("err_update_failed"));
      return data;
    }

    async function toggleSeries(id, mode) {
      const res = await apiFetch(`/api/series/${encodeURIComponent(id)}/${mode}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || t("err_update_failed"));
      return data;
    }

    async function optimisticToggle(id, mode, kind, buttonEl, options = {}) {
      const key = mode === "favorite" ? "is_favorite" : "is_watched";
      const activeClass = mode === "favorite" ? "active" : "active";
      const item = state.items.find((i) => i.id === id);
      const oldValue = item ? item[key] : (buttonEl.getAttribute("aria-pressed") === "true" ? 1 : 0);
      const newValue = oldValue ? 0 : 1;

      buttonEl.classList.toggle(activeClass, !!newValue);
      buttonEl.setAttribute("aria-pressed", String(!!newValue));
      if (item) item[key] = newValue;
      if (!currentSeriesId) {
        const countKey = mode === "favorite" ? "favorites" : "watched";
        state.sectionCounts[countKey] = Math.max(0, (state.sectionCounts[countKey] || 0) + (newValue ? 1 : -1));
        applyStats();
      }
      if (options.onOptimisticUpdate) options.onOptimisticUpdate(newValue);

      let removedCard = false;
      const section = currentSeriesId ? null : state.section;
      const shouldRemove = (section === "favorites" && mode === "favorite" && !newValue) ||
        ((section === "watched") && mode === "watched" && !newValue) ||
        (section === "continue" && mode === "watched");
      if (shouldRemove) {
        const card = buttonEl.closest("[data-item-id]");
        if (card) {
          card.remove();
          state.items = state.items.filter((i) => i.id !== id);
          state.matched = Math.max(0, state.matched - 1);
          if (section === "continue") {
            state.sectionCounts.continue = Math.max(0, (state.sectionCounts.continue || 0) - 1);
            applyStats();
          }
          removedCard = true;
          els.status.textContent = metadataStatusText() || t("status_shown", { shown: state.items.length, matched: formatCount(state.matched) });
        }
      }

      try {
        const data = kind === "series" ? await toggleSeries(id, mode) : await toggleItem(id, mode);
        if (item) item[key] = data[key];
        if (options.onSuccess) options.onSuccess(data);
        return data;
      } catch (error) {
        buttonEl.classList.toggle(activeClass, !!oldValue);
        buttonEl.setAttribute("aria-pressed", String(!!oldValue));
        if (item) item[key] = oldValue;
        if (!currentSeriesId) {
          const countKey = mode === "favorite" ? "favorites" : "watched";
          state.sectionCounts[countKey] = Math.max(0, (state.sectionCounts[countKey] || 0) + (oldValue ? 1 : -1));
          applyStats();
        }
        if (options.onRevert) options.onRevert(oldValue);
        if (removedCard) load(false).catch((err) => console.error(err));
        throw error;
      }
    }

    /* ---- Refresh ------------------------------------------------------------ */
    async function bootstrap() {
      const res = await apiFetch("/api/status");
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || t("err_update_failed"));
      state.metadataStatus = data.metadata_status || state.metadataStatus;
      applyStats();
      return data;
    }

    async function refreshLibrary() {
      els.refresh.disabled = true;
      els.status.textContent = t("refresh_running");
      try {
        const res = await apiFetch("/api/refresh", { method: "POST" });
        const data = await res.json();
        if (!res.ok) {
          if (res.status === 403) throw new Error(t("err_login_required"));
          throw new Error(data.detail || t("err_update_failed"));
        }
        state.lastRefresh = data.last_refresh;
        state.metadataStatus = { running: true, completed: 0, total: 0, error: null };
        applyStats();
        els.status.textContent = t("refresh_running");
        await load(false);
        els.status.textContent = t("refresh_done");
        loadSourceStatus();
      } catch (error) {
        els.status.textContent = error.message;
        loadSourceStatus();
      } finally {
        els.refresh.disabled = false;
      }
    }

    /* ---- Series detail -------------------------------------------------------- */
    function sortEpisodes(a, b) {
      return (a.season_number || 0) - (b.season_number || 0) || (a.episode_number || 0) - (b.episode_number || 0);
    }

    function nextUnwatchedEpisode(seasons) {
      const names = Object.keys(seasons).sort((a, b) => {
        const num = (s) => { const m = /(\d+)/.exec(s); return m ? parseInt(m[1], 10) : 0; };
        return num(a) - num(b);
      });
      for (const name of names) {
        const eps = [...(seasons[name] || [])].sort(sortEpisodes);
        const next = eps.find((ep) => !ep.is_watched);
        if (next) return next;
      }
      return null;
    }

    async function renderSeriesDetail(seriesId) {
      const res = await apiFetch(`/api/series/${encodeURIComponent(seriesId)}?new_window=${encodeURIComponent(state.newWindow || "refresh")}&_=${Date.now()}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || t("err_series_load"));
      const series = data.series;
      const seasons = data.seasons || {};
      const seasonNames = Object.keys(seasons).sort((a, b) => {
        const num = (s) => { const m = /(\d+)/.exec(s); return m ? parseInt(m[1], 10) : 0; };
        return num(a) - num(b);
      });
      const episodes = seasonNames.flatMap((name) => (seasons[name] || []).map((ep) => ({ ...ep, _season: name })));
      const watchedCount = episodes.filter((ep) => ep.is_watched).length;
      const totalCount = episodes.length;
      const nextEp = nextUnwatchedEpisode(seasons);
      const allWatched = totalCount > 0 && watchedCount >= totalCount;
      const pct = totalCount ? Math.min(100, Math.round((watchedCount / totalCount) * 100)) : 0;
      const backdrop = series.poster_url ? ` style="background-image:url('${esc(posterProxy(series.poster_url))}')"` : "";
      const rating = ratingOf(series);
      const year = yearOf(series.release_date);

      const episodeRow = (ep) => `
        <tr data-episode-id="${esc(ep.id)}">
          <td class="ep-num">${ep.season_number != null && ep.episode_number != null ? `S${String(ep.season_number).padStart(2, "0")} E${String(ep.episode_number).padStart(2, "0")}` : esc(ep.episode_label || "–")}</td>
          <td class="ep-title">${esc(ep.episode_label || ep.title)}</td>
          <td>
            <button type="button" class="ep-toggle${ep.is_watched ? " active" : ""}" data-episode-watched="${esc(ep.id)}" aria-pressed="${!!ep.is_watched}" aria-label="${esc(t("mark_episode_watched"))}" title="${esc(t("watched_label"))}">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m4.5 12.5 5 5 10-11"/></svg>
            </button>
          </td>
          <td><a class="button ghost ep-open" href="/watch/${encodeURIComponent(ep.id)}.m3u">${esc(t("btn_open"))}</a></td>
        </tr>`;

      els.seriesView.innerHTML = `
        <div class="crumbs"><a href="/">${esc(t("nav_library"))}</a> <span aria-hidden="true">/</span> ${esc(series.title)}</div>
        <div class="series-hero">
          <div class="series-backdrop"${backdrop} aria-hidden="true"></div>
          <div class="series-hero-inner">
            <div class="series-poster">${series.poster_url ? `<img src="${esc(posterProxy(series.poster_url))}" alt="${esc(t("poster_alt", { title: series.title }))}">` : `<div class="poster-fallback">${esc(t("fallback_series"))}</div>`}</div>
            <div class="series-info">
              <h2>${esc(series.title)}</h2>
              <div class="series-meta">
                ${year ? `<span>${esc(year)}</span>` : ""}
                ${rating ? `<span class="rating-badge"><svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4 6.1 20.5l1.2-6.5L2.5 9.4l6.6-.9z"/></svg>${esc(rating)}</span>` : ""}
                <span>${esc(t("episodes", { n: totalCount }))}</span>
              </div>
              ${series.description ? `<p class="series-desc">${esc(series.description)}</p>` : ""}
              <div class="series-progress-row">
                <div class="progress" role="progressbar" aria-valuenow="${watchedCount}" aria-valuemin="0" aria-valuemax="${totalCount}"><span style="width:${pct}%"></span></div>
                <div class="labels"><span>${esc(t("episodes_progress", { w: watchedCount, t: totalCount }))}</span><span>${pct}%</span></div>
              </div>
              <div class="series-actions">
                ${allWatched
                  ? `<button type="button" class="primary" disabled>${esc(t("btn_all_watched"))}</button>`
                  : nextEp
                    ? `<a class="button primary" href="/watch/${encodeURIComponent(nextEp.id)}.m3u">${esc(t("btn_next_episode"))}</a>`
                    : `<button type="button" class="primary" disabled>${esc(t("btn_no_episode"))}</button>`}
                <button type="button" class="button ghost" id="seriesFav" aria-pressed="${!!series.is_favorite}" aria-label="${esc(t("favorites_toggle"))}">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="${series.is_favorite ? "currentColor" : "none"}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20.5C7 16.5 3 13.2 3 9.3 3 6.4 5.2 4 8 4c1.6 0 3.1.8 4 2 .9-1.2 2.4-2 4-2 2.8 0 5 2.4 5 5.3 0 3.9-4 7.2-9 11.2z"/></svg>
                  ${series.is_favorite ? esc(t("btn_favorited")) : esc(t("btn_favorite"))}
                </button>
              </div>
            </div>
          </div>
        </div>
        <div class="season-tabs" role="tablist" aria-label="${esc(t("seasons"))}">
          ${seasonNames.map((name, idx) => `<button type="button" class="season-tab" role="tab" data-season="${esc(name)}" aria-selected="${idx === 0}">${esc(name)}</button>`).join("")}
        </div>
        <div id="episodeList"></div>
      `;

      const episodeList = document.getElementById("episodeList");
      const renderSeason = (name) => {
        const eps = [...(seasons[name] || [])].sort(sortEpisodes);
        episodeList.innerHTML = `
          <table class="episode-table">
            <thead><tr><th scope="col">${esc(t("col_number"))}</th><th scope="col">${esc(t("col_title"))}</th><th scope="col">${esc(t("col_watched"))}</th><th scope="col">${esc(t("col_actions"))}</th></tr></thead>
            <tbody>${eps.map(episodeRow).join("")}</tbody>
          </table>`;
      };
      renderSeason(seasonNames[0]);
      els.seriesView.querySelectorAll(".season-tab").forEach((tab) => {
        tab.addEventListener("click", () => {
          els.seriesView.querySelectorAll(".season-tab").forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
          renderSeason(tab.dataset.season);
        });
      });

      const favBtn = document.getElementById("seriesFav");
      favBtn.addEventListener("click", () => {
        optimisticToggle(seriesId, "favorite", "series", favBtn, {
          onSuccess: (data) => {
            favBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="${data.is_favorite ? "currentColor" : "none"}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20.5C7 16.5 3 13.2 3 9.3 3 6.4 5.2 4 8 4c1.6 0 3.1.8 4 2 .9-1.2 2.4-2 4-2 2.8 0 5 2.4 5 5.3 0 3.9-4 7.2-9 11.2z"/></svg> ${esc(data.is_favorite ? t("btn_favorited") : t("btn_favorite"))}`;
          },
        }).catch((error) => { els.status.textContent = error.message; });
        refreshSectionCountsOnly().catch(() => {});
      });

      els.seriesView.addEventListener("click", (event) => {
        const btn = event.target.closest("[data-episode-watched]");
        if (!btn) return;
        const epId = btn.dataset.episodeWatched;
        optimisticToggle(epId, "watched", "item", btn, {
          onSuccess: () => {
            const ep = episodes.find((e) => e.id === epId);
            if (ep) ep.is_watched = ep.is_watched ? 0 : 1;
            refreshSectionCountsOnly().catch(() => {});
          },
        }).catch((error) => { els.status.textContent = error.message; });
      });

      document.title = `${series.title} · M3U Library`;
    }

    /* ---- Events --------------------------------------------------------------- */
    function bindEvents() {
      let searchTimer = null;
      els.search.addEventListener("input", () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => load(false).catch((error) => { els.status.textContent = error.message; }), 300);
      });
      els.kind.addEventListener("change", () => load(false).catch((error) => { els.status.textContent = error.message; }));
      els.group.addEventListener("change", () => load(false).catch((error) => { els.status.textContent = error.message; }));
      els.sort.addEventListener("change", () => load(false).catch((error) => { els.status.textContent = error.message; }));
      els.lang.addEventListener("change", () => load(false).catch((error) => { els.status.textContent = error.message; }));
      els.uhd.addEventListener("change", () => load(false).catch((error) => { els.status.textContent = error.message; }));

      els.loadMore.addEventListener("click", () => load(true).catch((error) => { els.status.textContent = error.message; }));
      els.refresh.addEventListener("click", () => refreshLibrary().catch((error) => { els.status.textContent = error.message; }));

      document.querySelectorAll("[data-stat-section]").forEach((btn) => {
        btn.addEventListener("click", () => {
          if (currentSeriesId) {
            location.href = libraryUrlFor({ kind: els.kind.value, section: btn.dataset.statSection });
            return;
          }
          state.section = btn.dataset.statSection;
          updateTitle(); syncNav(); applyStats(); syncLibraryUrl();
          load(false).catch((error) => { els.status.textContent = error.message; });
        });
      });

      document.querySelectorAll("[data-nav-view]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const view = JSON.parse(btn.dataset.navView);
          if (currentSeriesId) { location.href = libraryUrlFor(view); return; }
          els.kind.value = view.kind || "";
          state.section = view.section || "all";
          updateTitle(); syncNav(); applyStats(); syncLibraryUrl();
          load(false).catch((error) => { els.status.textContent = error.message; });
        });
      });

      els.library.addEventListener("click", (event) => {
        /* Poster-Klick oeffnet denselben Ziel wie der Open-Button. */
        const poster = event.target.closest(".poster-wrap img, .poster-wrap .poster-fallback");
        if (poster) {
          const card = poster.closest("[data-item-id]");
          const open = card && card.querySelector(".ep-open");
          if (open) { open.click(); return; }
        }
        const picker = event.target.closest("[data-version-picker]");
        if (picker) {
          openVersionPicker(picker.dataset.versionPicker);
          return;
        }
        const reset = event.target.closest("[data-series-reset]");
        if (reset) {
          const id = reset.dataset.seriesReset;
          reset.disabled = true;
          apiFetch(`/api/series/${encodeURIComponent(id)}/watched`, { method: "POST" })
            .then(() => {
              const card = reset.closest("[data-item-id]");
              if (card) card.remove();
              state.items = state.items.filter((i) => i.id !== id);
              state.matched = Math.max(0, state.matched - 1);
              state.sectionCounts.continue = Math.max(0, (state.sectionCounts.continue || 0) - 1);
              applyStats();
              els.status.textContent = metadataStatusText() || t("status_shown", { shown: state.items.length, matched: formatCount(state.matched) });
            })
            .catch((error) => {
              reset.disabled = false;
              els.status.textContent = error.message;
            });
          return;
        }
        const fav = event.target.closest("[data-favorite],[data-series-favorite]");
        if (fav) {
          const isSeries = !!fav.dataset.seriesFavorite;
          const id = isSeries ? fav.dataset.seriesFavorite : fav.dataset.favorite;
          optimisticToggle(id, "favorite", isSeries ? "series" : "item", fav).catch((error) => { els.status.textContent = error.message; });
          return;
        }
        const watched = event.target.closest("[data-watched],[data-series-watched]");
        if (watched) {
          const isSeries = !!watched.dataset.seriesWatched;
          const id = isSeries ? watched.dataset.seriesWatched : watched.dataset.watched;
          optimisticToggle(id, "watched", isSeries ? "series" : "item", watched, {
            onSuccess: () => { if (state.section === "continue") load(false).catch(() => {}); },
          }).catch((error) => { els.status.textContent = error.message; });
        }
      });

      document.getElementById("updateBannerAction").addEventListener("click", () => {
        hideUpdateBanner();
        load(false).catch((error) => { els.status.textContent = error.message; });
      });

      const versionModal = document.getElementById("versionModal");
      document.getElementById("versionModalClose").addEventListener("click", closeVersionPicker);
      versionModal.addEventListener("click", (event) => {
        if (event.target === versionModal) closeVersionPicker();
      });
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeVersionPicker();
      });

      setInterval(() => {
        refreshMetadataStatus().catch((error) => console.error(error));
        checkForLibraryUpdates().catch((error) => console.error(error));
      }, 5000);
    }

    /* ---- Boot ------------------------------------------------------------------- */
    applyStaticI18n();
    updateTitle();
    await refreshAuthStatus();
    loadSourceStatus();
    bindEvents();

    const initialGroup = pageParams.get("group") || "";
    if (pageParams.get("q")) els.search.value = pageParams.get("q");
    if (pageParams.get("kind")) els.kind.value = pageParams.get("kind");
    if (pageParams.get("sort")) els.sort.value = pageParams.get("sort");
    if (pageParams.get("lang")) els.lang.value = pageParams.get("lang");
    if (pageParams.get("uhd") === "1") els.uhd.checked = true;
    if (pageParams.get("section")) {
      const KNOWN_SECTIONS = ["all", "new", "popular", "trending", "upcoming", "favorites", "watched", "continue"];
      const sectionParam = pageParams.get("section");
      if (KNOWN_SECTIONS.includes(sectionParam)) state.section = sectionParam;
    }
    if (pageParams.get("new_window")) state.newWindow = pageParams.get("new_window");

    if (currentSeriesId) {
      els.libraryView.hidden = true;
      els.seriesView.hidden = false;
      renderSeriesDetail(currentSeriesId).catch((error) => {
        els.seriesView.innerHTML = `<div class="empty">${esc(error.message)}</div>`;
      });
      refreshMetadataStatus().catch(() => {});
      refreshSectionCounts().catch(() => {});
      return;
    }

    updateTitle(); syncNav(); applyStats(); syncVersionFilterVisibility();

    const cache = loadCache();
    const currentParams = {
      kind: els.kind.value,
      section: state.section,
      sort: els.sort.value,
      search: els.search.value || "",
      group: initialGroup,
      newWindow: state.newWindow,
      lang: els.lang.value,
      uhd: els.uhd.checked ? "1" : "",
    };
    const cacheMatches = cache &&
      cache.kind === currentParams.kind &&
      cache.section === currentParams.section &&
      cache.sort === currentParams.sort &&
      cache.search === currentParams.search &&
      cache.group === currentParams.group &&
      cache.newWindow === currentParams.newWindow &&
      cache.lang === currentParams.lang &&
      cache.uhd === currentParams.uhd;

    let hadUsableCache = false;
    if (cacheMatches) {
      hadUsableCache = true;
      state.items = cache.items;
      state.matched = cache.matched;
      state.total = cache.total;
      state.groups = cache.groups || [];
      state.sectionCounts = cache.sectionCounts || state.sectionCounts;
      state.lastRefresh = cache.lastRefresh;
      updateGroups(state.groups);
      if (initialGroup && state.groups.includes(initialGroup)) els.group.value = initialGroup;
      renderLibrary();
    }

    bootstrap().then((data) => {
      const serverLastRefresh = data.last_refresh;
      if (!hadUsableCache) {
        return load(false).then(() => {
          if (initialGroup && state.groups.includes(initialGroup)) {
            els.group.value = initialGroup;
            return load(false);
          }
        });
      }
      if (serverLastRefresh && serverLastRefresh !== state.lastRefresh) {
        hideUpdateBanner();
        load(false).catch((error) => {
          showUpdateBanner();
          els.status.textContent = error.message;
        });
      }
    }).catch((error) => { els.status.textContent = error.message; });
  })();
  </script>
</body>
</html>"""


SETTINGS_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Settings · M3U Library</title>
  <style>
    :root {
      --bg: #12161b;
      --bg-2: #171d24;
      --panel: #1b222a;
      --panel-2: #232b34;
      --line: #2c3641;
      --text: #e9eef4;
      --muted: #8fa0ae;
      --accent: #2dd4bf;
      --accent-strong: #22b3a2;
      --accent-soft: rgba(45, 212, 191, 0.12);
      --success: #34d399;
      --error: #f87171;
      --warning: #fbbf24;
      --radius: 10px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
      background: var(--bg); color: var(--text); min-height: 100vh; font-size: 15px;
    }
    *:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px; }
    button, input, select { font: inherit; color: var(--text); background: var(--panel-2); border: 1px solid var(--line); border-radius: var(--radius); }
    select { padding: 8px 10px; min-height: 38px; cursor: pointer; }
    button { cursor: pointer; }
    button:hover { border-color: var(--accent); }
    button:disabled { opacity: 0.55; cursor: not-allowed; }
    .button { display: inline-flex; align-items: center; justify-content: center; gap: 8px; text-decoration: none; padding: 8px 14px; min-height: 38px; border-radius: var(--radius); border: 1px solid var(--line); background: var(--panel-2); color: var(--text); cursor: pointer; }
    .button:hover { border-color: var(--accent); }
    .primary { background: var(--accent); border-color: var(--accent); color: #0b2b27; font-weight: 700; }
    .primary:hover { background: var(--accent-strong); border-color: var(--accent-strong); }
    .ghost { background: transparent; }
    a { color: var(--accent); }

    .page { max-width: 760px; margin: 0 auto; padding: 28px 20px 64px; }
    header.top { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 22px; flex-wrap: wrap; }
    .brand { display: flex; align-items: center; gap: 10px; font-weight: 800; font-size: 18px; color: var(--accent); }
    h1 { margin: 0; font-size: 22px; }
    h2 { font-size: 1.05rem; margin: 0 0 14px; }
    .card {
      background: var(--panel); border: 1px solid var(--line);
      border-radius: var(--radius); padding: 20px; margin-bottom: 18px;
    }
    label { display: block; font-size: 0.9rem; font-weight: 600; margin: 16px 0 5px; }
    label:first-of-type { margin-top: 0; }
    .hint { font-size: 0.8rem; color: var(--muted); font-weight: 400; margin: 4px 0 0; }
    input[type="password"], input[type="text"] {
      width: 100%; padding: 9px 12px; min-height: 38px;
      background: var(--panel-2); color: var(--text);
    }
    input::placeholder { color: var(--muted); }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .row input { flex: 1; min-width: 0; }
    .status { margin-top: 12px; font-size: 0.9rem; min-height: 1.2em; color: var(--muted); }
    .status.ok { color: var(--success); }
    .status.err { color: var(--error); }
    .badge { font-size: 0.75rem; padding: 2px 8px; border-radius: 99px; border: 1px solid var(--line); color: var(--muted); }
    .badge.set { border-color: var(--success); color: var(--success); }

    .tabs { display: flex; gap: 6px; margin-bottom: 18px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
    .tab {
      background: transparent; border: none; border-bottom: 2px solid transparent;
      color: var(--muted); padding: 9px 14px; font-size: 14px; border-radius: 6px 6px 0 0;
    }
    .tab:hover { color: var(--text); }
    .tab[aria-selected="true"] { color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }
    .tab-panel[hidden] { display: none; }

    .source-status {
      display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
      border: 1px solid var(--line); border-radius: var(--radius);
      background: var(--panel-2); padding: 10px 14px; margin-top: 8px; font-size: 13.5px;
    }
    .source-status .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--muted); flex: none; }
    .source-status.ok { border-color: rgba(52, 211, 153, 0.4); }
    .source-status.ok .dot { background: var(--success); }
    .source-status.ok .text { color: var(--success); }
    .source-status.err { border-color: rgba(248, 113, 113, 0.4); }
    .source-status.err .dot { background: var(--error); }
    .source-status.err .text { color: var(--error); }
    .source-status.warn { border-color: rgba(251, 191, 36, 0.4); }
    .source-status.warn .dot { background: var(--warning); }
    .source-status.warn .text { color: var(--warning); }
    .source-status .meta { color: var(--muted); font-size: 12.5px; }
    .source-status .grow { flex: 1; }

    @media (max-width: 560px) {
      .page { padding: 18px 14px 48px; }
    }
  </style>
</head>
<body>
  <div class="page">
    <header class="top">
      <div class="brand">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M2 9h20"/><path d="M8 4v5"/></svg>
        <h1 data-i18n="settings_title">Einstellungen</h1>
      </div>
      <div class="row">
        <a href="/" class="button ghost" data-i18n="back_to_library">← Zur Bibliothek</a>
        <button id="logout" class="ghost" hidden data-i18n="btn_logout">Abmelden</button>
      </div>
    </header>

    <!-- Setup / Login -->
    <div id="authCard" class="card" hidden>
      <h2 id="authTitle">Admin-Anmeldung</h2>
      <form id="authForm">
        <label for="authPassword" data-i18n="lbl_password">Passwort</label>
        <input type="password" id="authPassword" autocomplete="current-password" required>
        <div id="authPassword2Wrap" hidden>
          <label for="authPassword2" data-i18n="lbl_password2">Passwort wiederholen</label>
          <input type="password" id="authPassword2" autocomplete="new-password">
        </div>
        <p class="hint" id="authHint"></p>
        <p><button type="submit" class="primary" id="authSubmit" data-i18n="btn_login">Anmelden</button></p>
        <div class="status" id="authStatus" aria-live="polite"></div>
      </form>
    </div>

    <!-- Einstellungen -->
    <div id="settingsCard" hidden>
      <div class="tabs" role="tablist" aria-label="Einstellungsbereiche">
        <button type="button" class="tab" role="tab" data-tab="library" aria-selected="true" data-i18n="tab_library">Bibliothek</button>
        <button type="button" class="tab" role="tab" data-tab="access" aria-selected="false" data-i18n="tab_access">Zugriff</button>
        <button type="button" class="tab" role="tab" data-tab="security" aria-selected="false" data-i18n="tab_security">Sicherheit</button>
      </div>

      <div class="tab-panel" id="tab-library" role="tabpanel">
        <div class="card">
          <h2 data-i18n="h_source_metadata">Quelle &amp; Metadaten</h2>
          <form id="settingsForm">
            <label for="M3U_URL" data-i18n="lbl_m3u_url">M3U-Playlist-URL</label>
            <div class="row">
              <input type="password" id="M3U_URL" autocomplete="off" placeholder="https://anbieter.example/playlist.m3u">
              <button type="button" class="ghost" data-toggle="M3U_URL" data-i18n="btn_show">Anzeigen</button>
              <button type="button" class="ghost" data-clear="M3U_URL" data-i18n="btn_delete">Löschen</button>
            </div>
            <p class="hint" data-i18n="hint_m3u">Der Playlist-Link deines Streaming-Anbieters. Gespeichert in der serverseitigen .env-Datei (Modus 0600), niemals in Git. Zugangsdaten in der URL werden in Logs und Statusmeldungen maskiert.</p>

            <div class="source-status" id="sourceStatusBox">
              <span class="dot" aria-hidden="true"></span>
              <span class="text" id="sourceStatusText">Quelle noch nicht geprüft</span>
              <span class="meta" id="sourceStatusMeta"></span>
              <span class="grow"></span>
              <button type="button" class="ghost" id="checkSourceBtn" data-i18n="btn_check_connection">Verbindung prüfen</button>
            </div>
            <div class="status" id="checkSourceStatus" aria-live="polite"></div>

            <label for="TMDB_API_KEY" data-i18n="lbl_tmdb_key">TMDB-API-Schlüssel (v3)</label>
            <div class="row">
              <input type="password" id="TMDB_API_KEY" autocomplete="off" placeholder="optional, falls Bearer-Token gesetzt">
              <button type="button" class="ghost" data-toggle="TMDB_API_KEY" data-i18n="btn_show">Anzeigen</button>
              <button type="button" class="ghost" data-clear="TMDB_API_KEY" data-i18n="btn_delete">Löschen</button>
            </div>

            <label for="TMDB_BEARER_TOKEN" data-i18n="lbl_tmdb_bearer">TMDB-Bearer-Token (v4)</label>
            <div class="row">
              <input type="password" id="TMDB_BEARER_TOKEN" autocomplete="off" placeholder="optional, falls API-Schlüssel gesetzt">
              <button type="button" class="ghost" data-toggle="TMDB_BEARER_TOKEN" data-i18n="btn_show">Anzeigen</button>
              <button type="button" class="ghost" data-clear="TMDB_BEARER_TOKEN" data-i18n="btn_delete">Löschen</button>
            </div>
            <p class="hint" data-i18n="hint_tmdb">Einer der beiden TMDB-Zugänge genügt für Metadaten zu Filmen und Serien. Erstellbar auf themoviedb.org → Einstellungen → API.</p>

            <label for="METADATA_LANGUAGE" data-i18n="lbl_meta_lang">Sprache der Metadaten</label>
            <div class="row">
              <input type="text" id="METADATA_LANGUAGE" autocomplete="off" placeholder="de-DE">
              <button type="button" class="ghost" data-clear="METADATA_LANGUAGE" data-i18n="btn_delete">Löschen</button>
            </div>
            <p class="hint" data-i18n="hint_meta_lang">TMDB-Sprachcode, z. B. de-DE, en-US, fr-FR.</p>

            <p><button type="submit" class="primary" data-i18n="btn_save">Änderungen speichern</button></p>
            <div class="status" id="settingsStatus" aria-live="polite"></div>
          </form>
        </div>

        <div class="card">
          <h2 data-i18n="language_heading">Anzeige</h2>
          <label for="uiLanguage" data-i18n="language_label">Sprache der Oberfläche</label>
          <select id="uiLanguage">
            <option value="en">English</option>
            <option value="de">Deutsch</option>
          </select>
          <p class="hint" data-i18n="language_hint">Gilt sofort in diesem Browser.</p>
        </div>
      </div>

      <div class="tab-panel" id="tab-access" role="tabpanel" hidden>
        <div class="card">
          <h2 data-i18n="h_external_clients">Externe Clients</h2>
          <p class="hint" data-i18n="hint_api_key">Skripte wie der systemd-Aktualisierungs-Timer authentifizieren sich über diesen Schlüssel im <code>X-API-Key</code>-Header gegen geschützte Endpunkte.</p>
          <p><span data-i18n="apikey_status">Status:</span> <span class="badge" id="badge-API_KEY">nicht gesetzt</span></p>
          <div class="row">
            <input type="text" id="API_KEY" readonly placeholder="••••">
            <button type="button" class="ghost" id="revealKey" data-i18n="btn_reveal">Anzeigen</button>
            <button type="button" class="ghost" id="regenKey" data-i18n="btn_regenerate">Neu generieren</button>
          </div>
          <div class="status" id="keyStatus" aria-live="polite"></div>
        </div>
      </div>

      <div class="tab-panel" id="tab-security" role="tabpanel" hidden>
        <div class="card">
          <h2 data-i18n="h_change_password">Admin-Passwort ändern</h2>
          <form id="passwordForm">
            <label for="currentPassword" data-i18n="lbl_current_pw">Aktuelles Passwort</label>
            <input type="password" id="currentPassword" autocomplete="current-password" required>
            <label for="newPassword" data-i18n="lbl_new_pw">Neues Passwort (mindestens 8 Zeichen)</label>
            <input type="password" id="newPassword" autocomplete="new-password" required>
            <label for="newPassword2" data-i18n="lbl_new_pw2">Neues Passwort wiederholen</label>
            <input type="password" id="newPassword2" autocomplete="new-password" required>
            <p><button type="submit" class="primary" data-i18n="btn_change_password">Passwort ändern</button></p>
            <div class="status" id="passwordStatus" aria-live="polite"></div>
          </form>
        </div>
      </div>
    </div>
  </div>

  <script>
__I18N_INLINE__
    let csrf = null;

    function setStatus(el, message, ok) {
      el.textContent = message || "";
      el.className = "status" + (ok === undefined ? "" : ok ? " ok" : " err");
    }

    async function apiFetch(url, options = {}) {
      const method = (options.method || "GET").toUpperCase();
      const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
      if (csrf && method !== "GET") headers["X-CSRF-Token"] = csrf;
      return fetch(url, Object.assign({}, options, { headers }));
    }

    /* Tabs */
    document.querySelectorAll(".tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach((t) => t.setAttribute("aria-selected", String(t === tab)));
        document.querySelectorAll(".tab-panel").forEach((panel) => { panel.hidden = panel.id !== `tab-${tab.dataset.tab}`; });
      });
    });

    /* Auth */
    function showAuth(setupRequired) {
      document.getElementById("authCard").hidden = false;
      document.getElementById("settingsCard").hidden = true;
      document.getElementById("logout").hidden = true;
      document.getElementById("authTitle").textContent = t(setupRequired ? "auth_title_setup" : "auth_title_login");
      document.getElementById("authHint").textContent = setupRequired ? t("auth_hint_setup") : "";
      document.getElementById("authPassword2Wrap").hidden = !setupRequired;
      document.getElementById("authSubmit").textContent = t(setupRequired ? "btn_create_password" : "btn_login");
      document.getElementById("authForm").onsubmit = (event) => {
        event.preventDefault();
        setupRequired ? doSetup() : doLogin();
      };
    }

    function showSettings() {
      document.getElementById("authCard").hidden = true;
      document.getElementById("settingsCard").hidden = false;
      document.getElementById("logout").hidden = false;
      loadSettings();
      loadSourceStatus();
    }

    async function doSetup() {
      const pw = document.getElementById("authPassword").value;
      const pw2 = document.getElementById("authPassword2").value;
      const status = document.getElementById("authStatus");
      if (pw !== pw2) return setStatus(status, t("err_pw_mismatch"), false);
      const res = await fetch("/api/auth/setup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: pw }) });
      const data = await res.json();
      if (!res.ok) return setStatus(status, data.detail || t("err_setup_failed"), false);
      csrf = data.csrf;
      setStatus(status, t("msg_password_created"), true);
      showSettings();
    }

    async function doLogin() {
      const pw = document.getElementById("authPassword").value;
      const status = document.getElementById("authStatus");
      const res = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: pw }) });
      const data = await res.json();
      if (!res.ok) return setStatus(status, data.detail || t("err_login_failed"), false);
      csrf = data.csrf;
      setStatus(status, t("msg_logged_in"), true);
      showSettings();
    }

    /* Settings */
    async function loadSettings() {
      const res = await apiFetch("/api/admin/settings");
      if (!res.ok) return;
      const data = await res.json();
      if (data.csrf) csrf = data.csrf;
      for (const [key, info] of Object.entries(data.keys)) {
        if (key === "API_KEY") {
          const badge = document.getElementById("badge-API_KEY");
          if (badge) {
            badge.textContent = info.set ? t("apikey_set") : t("apikey_not_set");
            badge.className = "badge" + (info.set ? " set" : "");
          }
          continue;
        }
        const input = document.getElementById(key);
        if (input) {
          // Maskierte Anzeigewerte nie in Eingabefelder schreiben:
          // ein leeres Feld bedeutet beim Speichern «unverändert lassen».
          input.value = info.value || "";
          if (info.set && !info.value) {
            input.placeholder = (info.masked || "••••") + t("keep_placeholder");
          }
        }
      }
    }

    /* Quellenstatus */
    const SOURCE_LABEL_KEYS = {
      not_configured: "src_not_configured",
      unknown: "src_unknown",
      checking: "src_checking",
      ok: "src_ok",
      auth_failed: "src_auth_failed",
      unreachable: "src_unreachable",
      invalid: "src_invalid",
      empty: "src_empty",
    };

    function checkedAge(checkedAt) {
      if (!checkedAt) return "";
      const ms = Date.now() - new Date(checkedAt).getTime();
      if (!Number.isFinite(ms) || ms < 0) return "";
      const min = Math.floor(ms / 60000);
      if (min < 1) return t("age_now");
      if (min < 60) return t("age_minutes", { n: min });
      const h = Math.floor(min / 60);
      if (h < 24) return t("age_hours", { n: h });
      return t("age_days", { n: Math.floor(h / 24) });
    }

    function renderSourceStatus(data) {
      const box = document.getElementById("sourceStatusBox");
      const cls = { ok: "ok", auth_failed: "err", unreachable: "err", invalid: "err", empty: "warn", unknown: "", not_configured: "warn", checking: "" }[data.state] || "";
      box.className = `source-status ${cls}`;
      document.getElementById("sourceStatusText").textContent = t(SOURCE_LABEL_KEYS[data.state] || "src_unknown");
      const meta = [];
      if (data.state === "ok" && data.entry_count != null) meta.push(t("entries_count", { n: Number(data.entry_count).toLocaleString(LOCALE) }));
      const age = checkedAge(data.checked_at);
      if (age) meta.push(age);
      document.getElementById("sourceStatusMeta").textContent = meta.join(" · ");
    }

    async function loadSourceStatus() {
      try {
        const res = await fetch("/api/source-status", { cache: "no-store" });
        if (!res.ok) return;
        renderSourceStatus(await res.json());
      } catch (error) { console.error(error); }
    }

    document.getElementById("checkSourceBtn").addEventListener("click", async () => {
      const status = document.getElementById("checkSourceStatus");
      const btn = document.getElementById("checkSourceBtn");
      btn.disabled = true;
      setStatus(status, t("checking_source"));
      try {
        const res = await apiFetch("/api/admin/source-status/check", { method: "POST", body: "{}" });
        const data = await res.json();
        if (!res.ok) {
          setStatus(status, data.detail || t("check_failed"), false);
        } else {
          renderSourceStatus(data);
          const okResult = data.state === "ok";
          setStatus(status, okResult ? t("check_ok") : t("check_done"), okResult);
        }
      } catch (error) {
        setStatus(status, error.message, false);
      } finally {
        btn.disabled = false;
      }
    });

    /* Formulare */
    const pendingClear = [];

    document.getElementById("settingsForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const status = document.getElementById("settingsStatus");
      const body = {};
      for (const key of ["M3U_URL", "TMDB_API_KEY", "TMDB_BEARER_TOKEN", "METADATA_LANGUAGE"]) {
        const value = document.getElementById(key).value.trim();
        if (value) body[key] = value;
      }
      if (pendingClear.length) body.clear = pendingClear.splice(0);
      const res = await apiFetch("/api/admin/settings", { method: "PUT", body: JSON.stringify(body) });
      const data = await res.json();
      if (!res.ok) return setStatus(status, data.detail || t("save_failed"), false);
      setStatus(status, t("saved"), true);
      loadSettings();
      loadSourceStatus();
    });

    document.querySelectorAll("[data-clear]").forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.dataset.clear;
        if (!confirm(t("confirm_delete"))) return;
        pendingClear.push(key);
        const input = document.getElementById(key);
        input.value = "";
        input.placeholder = t("deleted_placeholder");
      });
    });

    document.querySelectorAll("[data-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        const input = document.getElementById(button.dataset.toggle);
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        button.textContent = t(show ? "btn_hide" : "btn_show");
      });
    });

    document.getElementById("passwordForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const status = document.getElementById("passwordStatus");
      const current = document.getElementById("currentPassword").value;
      const next = document.getElementById("newPassword").value;
      if (next !== document.getElementById("newPassword2").value) return setStatus(status, t("err_pw_mismatch_new"), false);
      const res = await apiFetch("/api/admin/settings/password", { method: "POST", body: JSON.stringify({ current, new: next }) });
      const data = await res.json();
      if (!res.ok) return setStatus(status, data.detail || t("password_failed"), false);
      setStatus(status, t("password_changed"), true);
      event.target.reset();
    });

    document.getElementById("revealKey").addEventListener("click", async () => {
      const res = await apiFetch("/api/admin/settings?reveal=1");
      if (!res.ok) return;
      const data = await res.json();
      document.getElementById("API_KEY").value = (data.keys.API_KEY && data.keys.API_KEY.value) || "";
    });

    document.getElementById("regenKey").addEventListener("click", async () => {
      const status = document.getElementById("keyStatus");
      if (!confirm(t("confirm_regen"))) return;
      const res = await apiFetch("/api/admin/settings/api-key/regenerate", { method: "POST", body: "{}" });
      const data = await res.json();
      if (!res.ok) return setStatus(status, data.detail || t("key_regen_failed"), false);
      document.getElementById("API_KEY").value = data.api_key;
      setStatus(status, t("key_regenerated"), true);
    });

    /* Sprachwahl */
    const langSelect = document.getElementById("uiLanguage");
    langSelect.value = LANG;
    langSelect.addEventListener("change", () => {
      try { localStorage.setItem("m3u-lang", langSelect.value); } catch {}
      location.reload();
    });

    /* Statische Texte beim Start setzen */
    applyStaticI18n();
    document.title = t("settings_title") + " · M3U Library";

    document.getElementById("logout").addEventListener("click", async () => {
      await fetch("/api/auth/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      csrf = null;
      location.reload();
    });

    (async function boot() {
      const res = await fetch("/api/auth/status");
      const data = await res.json();
      if (data.authenticated) {
        csrf = data.csrf;
        showSettings();
      } else {
        showAuth(data.setup_required);
      }
    })();
  </script>
</body>
</html>"""

LIBRARY_HTML = LIBRARY_HTML.replace("__I18N_INLINE__", _I18N_JS)
SETTINGS_HTML = SETTINGS_HTML.replace("__I18N_INLINE__", _I18N_JS)
