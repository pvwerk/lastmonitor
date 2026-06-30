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

## PLEXLOG vorbereiten
Die native Modbus-TCP-Schnittstelle muss aktiv sein:
- **Port 503**, **UnitID 1**, **Input Register (FC4)**, Datentyp **int32**, Einheit **Watt**.
- **Register 0** = PV-Erzeugung, **Register 2** = Verbrauch / Netzbezug.
- Ohne PV-Anlage (typische Küche) liefert **Register 2** direkt den Netzbezug.

> Quelle der Registerbelegung: produktiv genutzte evcc-Community-Integration
> (github.com/evcc-io/evcc, Discussion #11661). Die offizielle Modbus-/Excel-Doku
> gibt es auf Anfrage bei Plexlog (info@plexlog.de). Mit dem **„Verbindung testen"**-
> Knopf in den Einstellungen lässt sich der gelesene Wert sofort am Gerät prüfen
> (z. B. einen Verbraucher einschalten und zusehen, wie der Wert steigt).

Alternativ ist das **OpenGateway-Profil** wählbar (Port 1502, Holding/Float/MW,
mit Phasen) – in den Einstellungen per Profil umschaltbar.

## Einstellungen (`/settings`)
- **Profil**: „PLEXLOG nativ" (Standard) oder „OpenGateway".
- **IP-Adresse**, Port, UnitID, Funktionscode, Datentyp, Skalierung.
- **Netzbezug ermitteln**: direkt aus einem Register, oder „Verbrauch − PV".
- **Grenzwerte**: maximale Anschlussleistung (kW), Warn-% (gelb), Kritisch-% (rot).
  - Tipp Anschlussleistung: Absicherung (A) × 3 × 230 V ÷ 1000.
- **Anzeige**: Titel, Warntexte, Phasen ein/aus, Aktualisierungsintervall.

## Updates einspielen
Auf dem Pi:
```bash
cd lastmonitor && bash deploy/update.sh
```
Holt den neuesten Stand aus GitHub und startet den Dienst neu.

## Lokal entwickeln / testen (Mac/PC)
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
# Anzeige:       http://localhost:8000/
# Einstellungen: http://localhost:8000/settings
```

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
