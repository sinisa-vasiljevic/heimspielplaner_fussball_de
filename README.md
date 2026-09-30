# Heimspielplaner V49.0
- Feste FUSSBALL.DE-Teamquellen für zehn Mannschaften.
- Stabile interne Spiel-ID aus offizieller Spielnummer, damit Verlegungen bestehende Zuordnungen behalten.
- Automatische Übernahme der auf der Teamseite ausgewiesenen Heimspielstätte.
- Netzwerkzuerst für `spiele-live.json` und `version.json`, Offline-Fallback bleibt erhalten.
- FuPa vollständig entfernt.

`spiele-live.json` ist bewusst nicht im Paket, damit der aktuelle Live-Datenstand beim Upload nicht überschrieben wird.
