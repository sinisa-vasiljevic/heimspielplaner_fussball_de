## Heimspielplaner V49.1
- Turnierspiele mit Wettbewerbstyp `TU` werden nicht als Heimspiele im Frankenstadion gewertet.
- Schutz ist doppelt umgesetzt: im FUSSBALL.DE-Sync und beim Einlesen in der App.
- Spielzeit, Wettbewerbstyp und Spielnummer werden nach jeder Begegnung zurückgesetzt, damit Werte nicht auf das nächste Turnierspiel übertragen werden.
- Die vorhandenen falschen TU-Einträge wurden aus `spiele-live.json` entfernt.
- Cache-Version wurde auf V49.1 erhöht, damit alte Live-Daten nicht weiter angezeigt werden.
- Backup-Wiederherstellung nutzt jetzt denselben Live-Cache-Schlüssel wie die laufende App.
- Alle bisherigen Funktionen für Heimspiele, Verkauf, freie Slots, Kabinen, Import/Export und Offline-Nutzung bleiben erhalten.
