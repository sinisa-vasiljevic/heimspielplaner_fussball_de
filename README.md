### Heimspielplaner 50.11

- Basis ist Version 50.10.
- FUSSBALL.DE-Spiele bleiben unverändert in `spiele-live.json`.
- Manuell angelegte Spiele bleiben lokal gespeichert und werden zusätzlich in `manuelle-spiele.json` im selben Repository synchronisiert.
- Der Trainingsplaner kann beide öffentlichen JSON-Dateien später ausschließlich lesend zusammenführen.
- Es gibt keine Firebase-Verbindung und keine Konten- oder Datenkopplung zwischen Heimspielplaner und Trainingsplaner.
- Der Schreibzugriff verwendet einen lokal gespeicherten, auf dieses Repository beschränkten GitHub Fine-grained Token.
