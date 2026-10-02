# WakeSync v10.1.0

## Branding
- Het C9-logo in de Raspberry Pi-GUI en `test2.pl` komt uit exact dezelfde aangeleverde bron.
- Het korte streepje in de `A` blijft daardoor gelijk aan het goedgekeurde logo.
- Thema's gebruiken een merkveilige achtergrond/omlijsting; de logopixels worden niet per thema herkleurd.

## Online beheer
- De tabnavigatie werkt weer met de bestaande strikte Content-Security-Policy via een per-request nonce.
- Zonder JavaScript blijven de beheerpanelen als fallback zichtbaar.
- Het primaire alarm kan optioneel een specifieke datum krijgen.
- De health-uitvoer blijft protocolversie 10 en meldt daarnaast release `10.1.0`.

## Alarm
- Nieuwe alarmflow: eerst datum of `Dagelijks`, daarna tijd.
- Uur- en minutenwijzer zijn dragbaar; de digitale tijd loopt tijdens het slepen live mee.
- Aan/uitbediening gebruikt smooth touchvriendelijke toggles.
- Datumalarmen zijn eenmalig; dagelijkse alarmen behouden het bestaande gedrag.

## Slaapstand
- `P` schakelt vanuit de normale GUI direct naar slaapstand voor demonstraties.
- Liquid Motion is teruggebracht naar minder banden, contouren en splinepunten en draait op een rustiger interval.
- Een renderfout in een slaapeffect stopt de GUI-eventloop niet.

## Bekende hardwarestatus
- De software wijzigt de touchdriver/Wayland-configuratie niet automatisch.
- Fysieke touch, speaker en lamp moeten op de echte Raspberry Pi/hardwareopstelling worden gevalideerd.
- De live MyX-feed moet worden gecontroleerd op werkelijk aangeleverde lokaalinformatie.
