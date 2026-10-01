# WakeSync v9.0.0

## Interface
- C9-logo als vaste branding toegevoegd.
- Nieuwe vierde navigatietab **Alarm**.
- 360° uur- en minutenkiezer voor alarmtijd.
- Alarmconfiguratie samengebracht op één scherm.
- Slaapmodus uitgebreid met uit/zachte gloed/pulse/aurora en instelbare intensiteit.
- Agenda toont zes regels per pagina en houdt ondernavigatie vrij.

## Agenda / MyX
- Bug opgelost waarbij `LOCATION:-` of `LOCATION:—` als echt lokaal werd
  geaccepteerd en verdere locatie-extractie stopte.
- Parser zoekt nu verder in DESCRIPTION, X-ALT-DESC, COMMENT, RESOURCES en
  vendorvelden.
- Regresstest toegevoegd voor een Project-les van 15:30–17:00.
- End-to-end test toegevoegd: ICS-lokaal → Vandaag → Agenda.

## Online beheer
- `test2.pl` naar schema/healthversie 9.
- Responsive desktop- en mobiele tabinterface.
- Tabs: Alarm, Weergave, Rooster en Systeem.
- Slaapeffect en gloedsterkte online instelbaar.
- C9-branding toegevoegd aan login- en beheerpagina.
- Openbare loginuitleg toont configureerbare categorieën zonder privédata.

## Tijd
- WakeSync gebruikt uitsluitend de lokale Raspberry Pi-systeemtijd voor de
  klokweergave en alarmberekening; geen netwerkrequest is nodig om tijd te tonen.
- Offline gedrag is getest op de SystemClock-laag.

## Touch
- Automatische touchcheck en automatische touchfix uit de product-GUI gehaald.
- Diagnose claimt niet langer dat de touchconfiguratie werkend is.
- De product-CLI bevat geen touch-check of automatische touchfix meer; onderzoek aan de ADS7846-configuratie gebeurt voortaan los van WakeSync.

## Compatibiliteit
- Updater, rollback, healthcheck, cloudrevision, agenda-cache en persistente
  alarmstatus uit v8 blijven behouden.
