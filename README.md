# Heimspielplaner V48.0

Vollständig geprüfter Aufbau ohne FuPa.

## Datenfluss

1. GitHub Actions ruft alle 3 Stunden zehn feste FUSSBALL.DE-Mannschaftsseiten ab.
2. `scripts/sync_fussball_de.py` schreibt ausschließlich Heimspiele nach `spiele-live.json`.
3. `index.html` lädt ausschließlich `spiele-live.json` und kein FuPa-Widget.
4. Der Service Worker behandelt `spiele-live.json` netzwerkzuerst, damit neue Termine nicht durch einen alten Cache blockiert werden.

## Erstinstallation

Den gesamten Inhalt dieses Pakets in den Repository-Stamm laden. Danach unter Actions den Workflow einmal manuell starten. Erst nach einem erfolgreichen Lauf enthält `spiele-live.json` die aktuellen Spiele.
