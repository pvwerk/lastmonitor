import base64, os
def b64(p):
    with open(p,"rb") as f: return base64.b64encode(f.read()).decode()
pv  = b64("/Users/gustafbot/Desktop/lastmonitor/static/pvwerk-logo.png")
sa  = b64("/Users/gustafbot/Desktop/lastmonitor/static/sampl-logo.png")
disp= b64("/tmp/lmshots/e01_demo.png")
sett= b64("/tmp/lmshots/u01_update.png")

html = f"""<!DOCTYPE html><html lang=de><head><meta charset=utf-8>
<style>
@page {{ size: A4; margin: 16mm 15mm 16mm 15mm; }}
* {{ box-sizing: border-box; }}
body {{ font-family: -apple-system,'Segoe UI',Arial,sans-serif; color:#13203a; font-size:11pt; line-height:1.5; }}
h1 {{ font-size:21pt; margin:0 0 2mm; color:#1b3a6b; }}
h2 {{ font-size:14pt; margin:7mm 0 2mm; color:#1b3a6b; border-bottom:2px solid #e2e8f0; padding-bottom:1mm; }}
h3 {{ font-size:12pt; margin:4mm 0 1mm; color:#21477f; }}
p {{ margin:0 0 2mm; }}
ul,ol {{ margin:0 0 3mm; padding-left:6mm; }}
li {{ margin:0 0 1mm; }}
.header {{ display:flex; align-items:center; justify-content:space-between; border-bottom:3px solid #1b3a6b; padding-bottom:3mm; margin-bottom:4mm; }}
.header .logos {{ display:flex; align-items:center; gap:6mm; }}
.header img.pv {{ height:13mm; }}
.header img.sa {{ height:14mm; background:#fff; border-radius:3mm; }}
.lead {{ color:#475569; font-size:10.5pt; }}
table {{ width:100%; border-collapse:collapse; margin:2mm 0 4mm; }}
th,td {{ border:1px solid #cbd5e1; padding:2mm 2.5mm; text-align:left; vertical-align:top; font-size:10pt; }}
th {{ background:#eef2f8; color:#1b3a6b; }}
td.k {{ width:42mm; font-weight:600; color:#21477f; }}
.box {{ background:#f1f5fb; border:1px solid #d4deec; border-radius:2mm; padding:3mm 4mm; margin:2mm 0 4mm; }}
.box.warn {{ background:#fff5f0; border-color:#f3c6ae; }}
code {{ background:#eef2f8; padding:.4mm 1.5mm; border-radius:1mm; font-size:9.5pt; }}
.shot {{ width:100%; border:1px solid #cbd5e1; border-radius:2mm; margin:2mm 0 1mm; }}
.cap {{ font-size:9pt; color:#64748b; margin-bottom:4mm; }}
.pagebreak {{ page-break-before: always; }}
.foot {{ margin-top:6mm; padding-top:2mm; border-top:1px solid #cbd5e1; font-size:8.5pt; color:#94a3b8; text-align:center; }}
.pill {{ display:inline-block; width:4mm; height:4mm; border-radius:50%; vertical-align:middle; margin-right:1.5mm; }}
</style></head><body>

<div class=header>
  <div><h1>Küchen&#8209;Lastmonitor</h1><div class=lead>Bedien&#8209; und Einstellungs&#8209;Anleitung</div></div>
  <div class=logos>
    <img class=sa src="data:image/png;base64,{sa}">
    <img class=pv src="data:image/png;base64,{pv}">
  </div>
</div>

<p>Der Küchen&#8209;Lastmonitor zeigt auf einem Monitor in der Küche laienverständlich den aktuellen
<b>Netzbezug</b> an und warnt, bevor der begrenzte Netzanschluss überlastet wird (damit keine Sicherung
herausfliegt). Die Werte kommen per Modbus&#8209;TCP direkt aus dem <b>PLEXLOG</b>. Diese Anleitung erklärt,
wie man auf das Gerät zugreift, wie man Einstellungen vornimmt und was jede Einstellung bedeutet.</p>

<h2>1&nbsp;· So greift man zu</h2>
<h3>Die Anzeige (Küchenmonitor)</h3>
<p>Die Anzeige startet nach dem Einschalten des Raspberry Pi <b>automatisch im Vollbild</b>. Es ist keine
Bedienung nötig. Wer sie an einem anderen Gerät ansehen will: im Browser
<code>http://&lt;PI&#8209;IP&gt;:8000/</code> öffnen.</p>

<h3>Die Einstellungen (von Handy, Tablet oder PC)</h3>
<p>Die Einstellungen ruft man bequem von einem beliebigen Gerät <b>im selben Netzwerk</b> auf – im Browser:</p>
<div class=box><b>http://&lt;PI&#8209;IP&gt;:8000/settings</b></div>
<p>Beispiel: ist der Pi unter der IP <code>192.168.1.50</code> erreichbar, lautet die Adresse
<code>http://192.168.1.50:8000/settings</code>.</p>

<h3>Die IP&#8209;Adresse des Pi finden</h3>
<ul>
  <li><b>Im Router</b> (z.&nbsp;B. FRITZ!Box): unter „Heimnetz → Netzwerk" nach dem Gerät
      (Name meist <i>raspberrypi</i> oder <i>lastmonitor</i>) suchen – dort steht die IP.</li>
  <li><b>Direkt nach der Installation</b> wird die IP im Terminal angezeigt
      („Einstellungen im Netz: http://…:8000/settings").</li>
  <li>Tipp: Im Router eine <b>feste IP</b> für den Pi vergeben, dann ändert sich die Adresse nie.</li>
</ul>

<h3>Direkter Zugriff auf den Pi (für Technik/Wartung)</h3>
<p>Per SSH von einem Rechner im selben Netz:</p>
<div class=box><code>ssh &lt;benutzer&gt;@&lt;PI&#8209;IP&gt;</code> &nbsp;— z.&nbsp;B. <code>ssh pi@192.168.1.50</code></div>
<p>Nützliche Befehle auf dem Pi:</p>
<table>
<tr><td class=k>Dienst&#8209;Status</td><td><code>sudo systemctl status lastmonitor</code></td></tr>
<tr><td class=k>Neu starten</td><td><code>sudo systemctl restart lastmonitor</code></td></tr>
<tr><td class=k>Live&#8209;Protokoll</td><td><code>journalctl -u lastmonitor -f</code></td></tr>
<tr><td class=k>Update (Alternative)</td><td><code>cd lastmonitor &amp;&amp; bash deploy/update.sh</code></td></tr>
</table>

<h2>2&nbsp;· Software aktualisieren &amp; zurückwechseln</h2>
<p>Ganz oben in den Einstellungen steht die Karte <b>„Software&#8209;Version &amp; Update"</b>:</p>
<ul>
  <li><b>Auf neueste Version aktualisieren</b> – holt die neueste Version aus GitHub und startet die
      Anzeige automatisch neu. Steht „Update verfügbar", gibt es etwas Neues.</li>
  <li><b>Frühere Version (zurückwechseln)</b> – Liste der letzten Versionen mit Knopf
      <i>„Auf diese Version"</i>. Damit kann man jederzeit auf eine der letzten Versionen zurück.</li>
</ul>
<div class=box>Eigene Einstellungen (IP, Grenzwerte usw.) und die Energie&#8209;Statistik bleiben bei Update und
Zurückwechseln <b>erhalten</b>.</div>

<div class=pagebreak></div>
<h2>3&nbsp;· Die Einstellungen im Detail</h2>

<h3>Verbindung zum PLEXLOG</h3>
<table>
<tr><th>Einstellung</th><th>Bedeutung</th></tr>
<tr><td class=k>Profil</td><td>Voreinstellung der technischen Werte. <b>PLEXLOG nativ</b> ist richtig (Port 503).</td></tr>
<tr><td class=k>IP&#8209;Adresse</td><td>Adresse des PLEXLOG im Netzwerk (steht im Plexlog/Router).</td></tr>
<tr><td class=k>Port / UnitID</td><td>Standard <b>503</b> bzw. <b>1</b>. Nur ändern, wenn vom Plexlog vorgegeben.</td></tr>
<tr><td class=k>Funktionscode / Datentyp</td><td>Technisch: <b>Input Register (FC4)</b>, <b>int32</b>. Nicht ändern.</td></tr>
<tr><td class=k>Skalierung</td><td>Rechnet Rohwert in kW um. Watt → <b>0.001</b>. Nicht ändern.</td></tr>
<tr><td class=k>Byte/Wort&#8209;Reihenfolge, Vorzeichen</td><td>Technische Feinheiten – Standard belassen. „Vorzeichen umkehren" nur, falls Bezug/Einspeisung vertauscht sind.</td></tr>
<tr><td class=k>Verbindung testen</td><td>Liest sofort einen Wert und zeigt ihn an – zum Prüfen, ob die Verbindung steht.</td></tr>
</table>

<h3>Netzbezug &amp; Erzeugung</h3>
<table>
<tr><th>Einstellung</th><th>Bedeutung</th></tr>
<tr><td class=k>Netzbezug ermitteln</td><td><b>Netzanalysegerät / Janitza (Reg 19/20)</b> – am genauesten, empfohlen, rechnet PV und Batterie korrekt heraus.<br>
<i>Verbrauch − PV</i> – wenn kein Analysegerät vorhanden (nur ohne Batterie korrekt).<br>
<i>Direktes Register</i> – Sonderfall ohne PV.</td></tr>
<tr><td class=k>Register Netzanalysegerät</td><td>Standard <b>19</b> (Reg 19/20). Nur bei abweichendem Plexlog ändern.</td></tr>
<tr><td class=k>Register Verbrauch / Erzeugung</td><td>Standard <b>2</b> bzw. <b>0</b>. Quelle für Gesamtverbrauch und PV&#8209;Erzeugung.</td></tr>
</table>
<p class=lead>Gesamtverbrauch = Netzbezug + Erzeugung (wird automatisch berechnet).</p>

<h3>Grenzwerte (Netzanschluss) – das Wichtigste für den Schutz</h3>
<table>
<tr><th>Einstellung</th><th>Bedeutung</th></tr>
<tr><td class=k>Max. Anschlussleistung (kW)</td><td>Die <b>100&nbsp;%</b>&#8209;Marke. Faustformel: <b>Absicherung (A) × 3 × 230&nbsp;V ÷ 1000</b>.
   Beispiel 63&nbsp;A: 63 × 3 × 230 ÷ 1000 ≈ <b>43&nbsp;kW</b>.</td></tr>
<tr><td class=k>Warnung ab (%)</td><td>Ab hier wird alles <b>gelb</b> (z.&nbsp;B. 80&nbsp;%).</td></tr>
<tr><td class=k>Kritisch ab (%)</td><td>Ab hier <b>rote Vollbild&#8209;Warnung</b> „Strom reduzieren" (z.&nbsp;B. 95&nbsp;%).</td></tr>
</table>

<h3>Zähler (S0 / Modbus) &amp; Register&#8209;Scanner</h3>
<p>Felder, um zusätzliche, <b>eigene</b> Modbus&#8209;Zähler einzubinden (Name, Register usw.). Der
Register&#8209;Scanner liest live Register aus, um unbekannte Werte zu finden.
<b>Hinweis:</b> Einzelne am Plexlog angeschlossene Zähler gibt der Plexlog über Modbus nicht einzeln aus –
nur die Summen. Diese Felder sind für später / eigene Zähler gedacht.</p>

<h3>Anzeige</h3>
<table>
<tr><td class=k>Titel</td><td>Überschrift über dem Tacho.</td></tr>
<tr><td class=k>Warntext / Kritisch&#8209;Text</td><td>Texte für Gelb bzw. die rote Vollbild&#8209;Warnung.</td></tr>
<tr><td class=k>Aktualisierungsintervall</td><td>Wie oft gelesen wird (Sekunden). Hinweis: der Plexlog liefert nur alle ~15&nbsp;s neue Werte.</td></tr>
</table>
<p class=lead>Nach jeder Änderung unten auf <b>Speichern</b> – die Anzeige übernimmt die Werte automatisch.</p>

<div class=pagebreak></div>
<h2>4&nbsp;· Die Anzeige verstehen</h2>
<img class=shot src="data:image/png;base64,{disp}">
<div class=cap>Beispielanzeige (Demo&#8209;Werte).</div>
<table>
<tr><td class=k>Links: Netzbezug</td><td>Großer Tacho = aktuelle Last aus dem Netz. Darunter Auslastung in % und der
   <b>Gesamtverbrauch</b>. Die Statuszeile zeigt <b><span class=pill style="background:#16a34a"></span>Netzbezug</b>
   oder <b><span class=pill style="background:#38bdf8"></span>Einspeisung</b>.</td></tr>
<tr><td class=k>Rand&#8209;Ring</td><td>Farbiger Rahmen ums ganze Bild: <b><span class=pill style="background:#16a34a"></span>grün</b> ok,
   <b><span class=pill style="background:#f59e0b"></span>gelb</b> Warnung, <b><span class=pill style="background:#dc2626"></span>rot</b> kritisch.</td></tr>
<tr><td class=k>Rechts oben: Erzeugung</td><td>Aktuelle PV&#8209;Erzeugung (falls PV vorhanden).</td></tr>
<tr><td class=k>Rechts unten: Energie</td><td>Tagesertrag und Tagesverbrauch, darunter Woche und Monat (kWh).</td></tr>
<tr><td class=k>Rote Vollbild&#8209;Warnung</td><td>Erscheint ab dem kritischen Wert: <b>„STROM REDUZIEREN!"</b> – unübersehbar für alle in der Küche.</td></tr>
</table>

<h2>5&nbsp;· Wenn etwas nicht geht</h2>
<table>
<tr><th>Problem</th><th>Lösung</th></tr>
<tr><td class=k>„Keine Verbindung"</td><td>IP&#8209;Adresse prüfen, ist der Plexlog im selben Netz? „Verbindung testen" nutzen.</td></tr>
<tr><td class=k>Anzeige bleibt schwarz</td><td>Pi neu starten. Ggf. <code>sudo systemctl restart lastmonitor</code>.</td></tr>
<tr><td class=k>Werte wirken falsch</td><td>Netzbezug&#8209;Quelle prüfen (am besten „Netzanalysegerät"). „Vorzeichen umkehren" testen.</td></tr>
<tr><td class=k>Woche/Monat steht auf 0</td><td>Normal nach Erstinstallation – zählt ab Messbeginn hoch.</td></tr>
</table>

<div class=foot>Küchen&#8209;Lastmonitor · PHOTOVOLTAIK WERK · Quellcode &amp; Updates: github.com/pvwerk/lastmonitor</div>
</body></html>"""
open("/tmp/anleitung.html","w").write(html)
print("HTML geschrieben:", len(html), "Zeichen")
