# WakeSync 10.2.2 — Gerichte hotfix

## Kerncorrecties
- `AlarmClock.dismiss(physical=False, *, touchscreen=False)` accepteert een
  expliciete touchscreenactie zonder de oude ongeautoriseerde aanroep toe te staan.
- Tk overlay toont twee grote knoppen, waarvan "Alarm stoppen" ook tijdens Snooze actief blijft.
- Premium + klassieke GUI + browserdashboard tonen geen lampbediening zolang er
  uitsluitend MockLamp bestaat; opgeslagen schema/instellingen blijven compatibel.

## Audio
- `kies_audioapparaten()` kiest optioneel een ALSA Pulse/PipeWire PCM als er een
  lokale socketsessie aanwezig is en die route door `aplay -L` wordt vermeld.
- Herkent USB-Audio in `/proc/asound/cards` en gebruikt `plughw:CARD=<ID>,DEV=0`
  zodat de gekozen kaart niet afhankelijk is van een wisselend kaartnummer.
- ALSA-fouten worden in `AplaySpeaker.last_error` bewaard en in de GUI/website
  zichtbaar gemaakt. Fallback naar HDMI bij gedetecteerde USB wordt vermeden.
- Handmatige device-override: `WEKKER_AUDIO_DEVICE` of
  `~/.config/wakesync/audio-device.txt`; geen extra Python-pakketten vereist.

## Behoud
- Geen wijzigingen aan labwc, udev, boot overlays, MyX of gebruikersgegevens.
- Bestaande desktopintegratie uit 10.2.1 blijft behouden.
- Installer controleert exact de geüploade 10.2.1-bron, met LF/CRLF-tolerantie.
- Bestaande tests die nog een lampknop verwachtten zijn op de nieuwe,
  bewust lampvrije interface aangepast.

## QA
- 91 tests geslaagd: kern, GUI-acties, 4 thema's, audiofallback en bestaande regressies.
- Virtueel 800×480 Tk-scherm: alarm en snooze, beide met bedienbare stopknop.
- Browser-JavaScript met `node --check` gecontroleerd.
- Installer `--check` en `--apply` getest op nagebootste Windows-checkout.
- Geen echte Raspberry Pi- of audiohardware beschikbaar voor deze tests.
