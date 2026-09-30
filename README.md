# Heimspielplaner V46.0 – sicherer Offline-Start

## Änderungen
- Robuster Service Worker: Eine fehlerhafte optionale Datei verhindert nicht mehr das Speichern der gesamten App.
- `index.html` ist Pflichtbestandteil des Offline-Caches und wird gesondert geprüft.
- Sicherer Navigations-Fallback: Statt eines schwarzen oder weißen Bildschirms erscheint notfalls eine verständliche Offline-Meldung.
- Lokale Dateien werden auch bei URL-Parametern zuverlässig aus dem Cache gefunden.
- Fehlerhafte HTTP-Antworten werden nicht als gültige App-Seite gespeichert.
- Alte Heimspielplaner-Caches werden bei Aktivierung von V46.0 entfernt.
- FuPa wird erst nach dem sichtbaren App-Start und nur bei bestehender Onlineverbindung geladen.
- Versionsstand, Manifest-Verweis, Cache-Name und Versionsdatei wurden auf V46.0 vereinheitlicht.
- Vorhandene LocalStorage-Schlüssel und gespeicherte Nutzerdaten bleiben unverändert.

## Installation
1. Alle Dateien aus dieser ZIP gemeinsam in denselben GitHub-Pages-Ordner hochladen und vorhandene Dateien ersetzen.
2. Warten, bis GitHub Pages die Änderungen veröffentlicht hat.
3. Die bisherige Homescreen-App auf dem iPhone löschen.
4. Die Seite einmal vollständig online in Safari öffnen und kurz geöffnet lassen.
5. Erneut zum Home-Bildschirm hinzufügen und einmal online starten.
6. Danach im Flugmodus schließen und erneut öffnen.

## Enthaltene Dateien
`index.html`, `manifest.webmanifest`, `sw.js`, `version.json`, drei App-Icons und `README.md`.
