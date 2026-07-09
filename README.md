# Küchen-Lastmonitor (PLEXLOG PL 100)

Zeigt auf einem Monitor in der Küche **laienverständlich** den aktuellen
**Netzbezug** an und warnt, bevor der begrenzte Netzanschluss überlastet wird
(Sicherung fliegt raus). Läuft auf einem **Raspberry Pi** und liest die Werte
per **Modbus TCP** direkt aus dem **PLEXLOG PL 100**.

## Was es anzeigt
- Großer **Tacho** + Zahl: aktuell gezogene Leistung (kW).
- **Auslastung in %** der maximalen Anschlussleistung.
- **Farbiger Rand-Ring** rund um den Bildschirm – grün / gelb / rot, permanent sichtbar.
- **Rote Vollbild-Warnung** „STROM REDUZIEREN!", sobald es kritisch wird.
- Optional einzelne Phasen L1/L2/L3 (nur OpenGateway-Profil).

Bedienung ist nicht nötig – die Anzeige läuft im Vollbild. **Einstellungen**
macht der Elektromeister von einem anderen Rechner im selben Netzwerk über den
Browser: `http://<pi-ip>:8000/settings`.

## Hardware
- Raspberry Pi (3/4/5), per Netzwerk mit dem PLEXLOG verbunden.
- 27"-Monitor (kein Touch nötig) per HDMI, Pi hinten am Monitor montiert.

## Installation auf dem Raspberry Pi
```bash
git clone https://github.com/pvwerk/lastmonitor.git
cd lastmonitor
bash deploy/install.sh
sudo reboot
```
Nach dem Neustart startet die Anzeige automatisch im Vollbild.

## PLEXLOG vorbereiten (OpenGateway)
Im Plexlog muss das **OpenGateway** aktiv sein (Einstellungen → OpenGateway):
- **Port 503**, **Modbus TCP**, **Input Register (FC4)**, Datentyp **Signed int32**, Einheit **Watt**.
- Werte aktualisieren sich im Plexlog nur **alle ~15 s**.

Wichtigste Register (verifiziert, Doku „PLOpenGateway_Definitionen.xlsx"):
| Register | Bedeutung |
|---|---|
| 0/1 | Wirkleistung AC = **Erzeugung (PV)** |
| 2/3 | **Verbrauch Momentan** = Gesamtverbrauch |
| 19/20 | **Netzanalysegerät (Janitza)** = exakter Netzbezug (empfohlen) |
| 4 / 6 | Tagesertrag / Tagesverbrauch (Wh) |
| 8(+10) / 11(+13) | Gesamtertrag / Gesamtverbrauch (Wh, mit Exponent) |
| 36 / 37–38 | Batterie SOC % / Leistung |

> **Netzbezug-Quelle:** am genauesten ist **Reg 19/20 (Netzanalysegerät)** – rechnet
> Batterie/PV korrekt heraus. Ohne Analysegerät: „Verbrauch − Erzeugung" (nur ohne Batterie korrekt).
> Hinweis: Einzelne angeschlossene Zähler gibt der Plexlog über Modbus **nicht** einzeln aus – nur Summen.

## Einstellungen (`/settings`)
- **Software-Version & Update**: aktuelle Version, Knopf „Aktualisieren" (holt neueste Version aus GitHub),
  und Zurückwechseln auf eine frühere Version.
- **Verbindung**: IP-Adresse, Port, UnitID, Funktionscode, Datentyp, Skalierung. Knopf „Verbindung testen".
- **Netzbezug ermitteln**: Netzanalysegerät (Reg 19/20) / Verbrauch − PV / direktes Register.
- **Grenzwerte**: maximale Anschlussleistung (kW), Warn-% (gelb), Kritisch-% (rot).
  - Tipp Anschlussleistung: Absicherung (A) × 3 × 230 V ÷ 1000.
- **Energie**: Tagesertrag/-verbrauch + Woche/Monat (aus dem Gesamtzähler berechnet).
- **Anzeige**: Titel, Warntexte, Aktualisierungsintervall.
- **Standby-Zeitfenster**: je Wochentag eigenes „AN von/bis" (mit „wie Vortag"-Häkchen);
  außerhalb des Fensters dunkelt die Anzeige komplett ab. Software-Overlay, kein Hardware-DPMS
  (auf diesem Pi unter Wayland/labwc nicht sicher steuerbar).
- **Kosten (Verbrauch/Eigenverbrauch)**: Bezugskosten + PV-Strom-Kosten (€/kWh) eintragen,
  daraus werden Verbrauch, Eigenverbrauch (aus eigener PV gedeckter Anteil) und Kosten für
  Heute + Vortag laufend im Hintergrund berechnet (`daily_costs.json`, gitignored) und in
  den Einstellungen angezeigt. Auf der Küchen-Anzeige nur sichtbar, wenn „Auf der
  Küchen-Anzeige zeigen" aktiviert ist (dann wandert die Erzeugung klein nach links unten,
  1/3 Höhe, rechts oben stehen die Kosten-Karten; „Heute" aktualisiert sich dort alle 60 s).
- **SMS-Benachrichtigung**: jeder kann sich das selbst einrichten, unabhängig von den
  übrigen Einstellungen — eigener kostenloser Account bei
  [app.seven.io/signup](https://app.seven.io/signup?create_account) (0,50 € Testguthaben),
  API-Key + eigene Telefonnummer + eigene Schwelle (%) eintragen. Schickt bei
  Überschreiten eine SMS, danach Erinnerungen im eingestellten Abstand
  (Minimum 1 Minute), optional eine „wieder normal"-SMS. Test-Knopf vorhanden.
  Zusätzlich abschaltbar: Alarm bei **Verbindungsverlust zum Messgerät**
  (Standard: nach 3 Min. durchgehend offline) — denn ohne Verbindung wird
  auch die Überlast-Schwelle nicht überwacht. Hinweis: Fällt das Internet
  selbst aus, kann in dem Moment keine SMS raus.

## Updates einspielen
**Am einfachsten:** in den Einstellungen (`/settings`) den Knopf **„Auf neueste Version aktualisieren"**.
Alternativ auf dem Pi:
```bash
cd lastmonitor && bash deploy/update.sh
```
Beides holt den neuesten Stand aus GitHub und startet die Anzeige neu.

## Lokal entwickeln / testen (Mac/PC)
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
# Anzeige:       http://localhost:8000/
# Einstellungen: http://localhost:8000/settings
```

## Fernwartung / Ferndiagnose (`remote_report`)
Läuft der Pi an einem anderen Standort (z. B. bei einem Kunden, nicht im
selben Netzwerk), ist `/settings` von hier aus nicht mehr erreichbar. Dafür
schickt der Pi sich bei aktivierter `remote_report`-Einstellung
(`config.json`) alle `interval_s` Sekunden einen vollständigen
Selbst-Bericht (Hostname, lokale IP, Modbus-Konfiguration, Software-Version,
Live-Status inkl. Fehlermeldung) an einen kleinen Endpoint im PVWERK-CRM
(`api/external/device-report.js`, Tabelle `external_device_reports`).
Authentifizierung per geteiltem Secret, kein Login nötig. Enthält bewusst
**keine** Geheimnisse (SMS-API-Key wird nur als „gesetzt: ja/nein" gemeldet).

```json
"remote_report": {
  "enabled": true,
  "endpoint": "https://crm.photovoltaikwerk.de/api/external/device-report",
  "secret": "<geteiltes Secret, aus system_settings.external_device_reports_secret>",
  "device_source": "lastmonitor-sampl",
  "interval_s": 60
}
```
Status des letzten Versands: `GET /api/remote-report/status`.

## Aufbau
```
app.py              FastAPI-Server (Anzeige, Einstellungen, API, SSE-Livestream)
modbus_reader.py    Modbus-TCP-Leser (Hintergrund-Thread, int32/float, FC3/FC4)
config.example.json Standard-Konfiguration (wird zu config.json kopiert)
static/             Anzeige + Einstellungen (HTML/CSS/JS)
deploy/             install.sh, update.sh, kiosk.sh (Raspberry-Pi-Setup)
```

## Hinweis zur „Einzelmessung pro Pfanne"
Die native Modbus-Schnittstelle liefert **aggregierte** Werte (Netzbezug, PV),
**kein** Auslesen einzelner Verbraucher/Ports. Die Software ist über die
Konfiguration (zusätzliche „channels") erweiterbar, falls Plexlog dafür ein
Profil mit entsprechenden Registern bereitstellt.
