"""WakeSync-agendareparatie: toon lesdagen vanuit de al gevulde cache.

De MyX-feed blijft ongewijzigd. Dit bestand leest uitsluitend de bestaande
AgendaCache en past de navigatie en de samenvatting van het hoofdscherm aan.
Er wordt niets veranderd aan alarmen, netwerkverkeer of feedinstellingen.
"""
from __future__ import annotations

from dataclasses import is_dataclass, replace
from datetime import date
import logging
from typing import Any

log = logging.getLogger(__name__)

# Voor de UI doorzoeken we alleen kalenderdagen die al in de cache zijn geladen.
# Er worden hier dus geen netwerkverzoeken op de Tkinter-hoofdthread uitgevoerd.
MAX_LOOKAHEAD = 90
MAANDEN = (
    "", "jan", "feb", "mrt", "apr", "mei", "jun",
    "jul", "aug", "sep", "okt", "nov", "dec",
)


def gevulde_lesdagen(cache: Any, vandaag: date, bereik: int = MAX_LOOKAHEAD) -> list[date]:
    """Geef bestaande cachedatums met minimaal één les, zonder lesinhoud te loggen."""
    datums: list[date] = []
    try:
        status = cache.status_dict()
        sleutels = status.get("loaded_days", ())
        if not sleutels:
            sleutels = status.get("cached_days", ())
    except (AttributeError, TypeError, ValueError):
        sleutels = getattr(cache, "days", {}).keys()

    for sleutel in sleutels:
        try:
            dag = date.fromisoformat(str(sleutel))
            if abs((dag - vandaag).days) > bereik:
                continue
            if cache.get_day(dag):
                datums.append(dag)
        except (TypeError, ValueError, AttributeError, KeyError):
            # Een beschadigde/dubbele dag kan geen andere cache-dag verbergen.
            continue
    return sorted(set(datums))


def zoek_lesdag(
    cache: Any,
    vanaf: date,
    richting: int = 1,
    *,
    inclusief: bool = False,
) -> date | None:
    """Vind de eerste gevulde lesdag vóór of na een datum."""
    if richting not in (-1, 1):
        raise ValueError("richting moet -1 of 1 zijn")
    for dag in sorted(
        gevulde_lesdagen(cache, vanaf),
        reverse=(richting == -1),
    ):
        if richting == 1 and (dag > vanaf or inclusief and dag == vanaf):
            return dag
        if richting == -1 and (dag < vanaf or inclusief and dag == vanaf):
            return dag
    return None


def _komende_les(cache: Any, vandaag: date) -> tuple[date, Any] | None:
    """Zoek de eerstvolgende toekomstige les, nooit een les uit het verleden."""
    dag = zoek_lesdag(cache, vandaag, richting=1)
    if dag is None:
        return None
    try:
        lessen = cache.get_day(dag)
        geldig = [les for les in lessen if hasattr(les, "start")]
        if geldig:
            return dag, min(geldig, key=lambda les: les.start)
    except (TypeError, AttributeError, ValueError):
        pass
    return None


def _vul_volgende_les_in(data: Any, cache: Any, vandaag: date) -> Any:
    """Laat Vandaag de volgende les zien wanneer er vandaag niets meer aankomt."""
    main = getattr(data, "main", None)
    if main is None or not is_dataclass(main):
        return data
    if getattr(main, "lesson_label", "") not in ("VANDAAG", "ROOSTER"):
        return data

    match = _komende_les(cache, vandaag)
    if match is None:
        return data
    dag, les = match
    start = les.start
    einde = getattr(les, "end", None)
    tijd = start.strftime("%H:%M")
    if einde is not None and hasattr(einde, "strftime"):
        tijd += f" – {einde:%H:%M}"
    update = replace(
        main,
        lesson_label=f"VOLGENDE LES · {dag.day} {MAANDEN[dag.month].upper()}",
        lesson_subject=str(getattr(les, "subject", "") or "Les"),
        lesson_time=tijd,
        lesson_room=str(getattr(les, "room", "") or ""),
        lesson_teacher=str(getattr(les, "teacher", "") or ""),
    )
    try:
        if is_dataclass(data):
            return replace(data, main=update)
        data.main = update
    except (TypeError, AttributeError):
        pass
    return data


def install_agenda_fix(app_klasse: type) -> bool:
    """Installeer de patch eenmalig op TouchApp (werkt ook met PremiumTouchApp).

    Een niet-standaard testdummy zonder de juiste methoden wordt ongemoeid
    gelaten. Daardoor breken oudere GUI-tests niet door importbijwerkingen.
    """
    if getattr(app_klasse, "_wakesync_agenda_fix_installed", False):
        return False
    nodig = ("_data", "_shift_agenda_day", "_agenda_today")
    if any(not callable(getattr(app_klasse, naam, None)) for naam in nodig):
        return False

    originele_data = app_klasse._data
    originele_shift = app_klasse._shift_agenda_day
    originele_today = app_klasse._agenda_today

    def data_met_toekomst(self: Any) -> Any:
        data = originele_data(self)
        try:
            context = self._runtime.ctx
            vandaag = context.clock.now().date()
            scherm = getattr(getattr(self, "_nav", None), "current", None)
            scherm = getattr(scherm, "value", scherm)
            geselecteerd = getattr(self, "_agenda_day", None) or vandaag

            # Dit werkt ook wanneer de ICS-cache pas NA het starten van de
            # GUI gevuld wordt: iedere normale render kan de volgende lesdag
            # vinden zodra de achtergrond-sync voltooid is.
            bewust_vandaag = (
                getattr(self, "_wakesync_handmatig_vandaag", None) == vandaag
            )
            if (
                scherm == "agenda"
                and geselecteerd == vandaag
                and not bewust_vandaag
                and not context.cache.get_day(vandaag)
            ):
                volgende = zoek_lesdag(context.cache, vandaag)
                if volgende is not None:
                    self._agenda_day = volgende
                    self._agenda_page = 0
                    data = originele_data(self)

            return _vul_volgende_les_in(data, context.cache, vandaag)
        except (AttributeError, TypeError, ValueError):
            # Nooit de hoofd-GUI laten uitvallen door een statuskaart.
            log.exception("Agendadatum of volgende les bepalen niet gelukt")
            return data

    def schuif_lesdag(self: Any, dagen: int) -> Any:
        # De pijltjes gaan naar de vorige/volgende gevulde LESDAG, in plaats
        # van tientallen lege dagen te vereisen. Zonder zo'n dag blijft het
        # oorspronkelijke dag-voor-daggedrag beschikbaar.
        if dagen in (-1, 1):
            try:
                context = self._runtime.ctx
                huidig = getattr(self, "_agenda_day", None) or context.clock.now().date()
                gevonden = zoek_lesdag(context.cache, huidig, dagen)
                if gevonden is not None:
                    self._agenda_day = gevonden
                    self._agenda_page = 0
                    return self.render()
            except (AttributeError, TypeError, ValueError):
                log.exception("Lesdag bladeren mislukt; oorspronkelijke navigatie gebruikt")
        return originele_shift(self, dagen)

    def terug_naar_vandaag(self: Any) -> Any:
        # 'Nu' is een bewuste keuze. De automatische sprong geldt pas weer
        # op een nieuwe kalenderdag of na een herstart van de GUI.
        try:
            self._wakesync_handmatig_vandaag = self._runtime.ctx.clock.now().date()
        except AttributeError:
            pass
        return originele_today(self)

    app_klasse._data = data_met_toekomst
    app_klasse._shift_agenda_day = schuif_lesdag
    app_klasse._agenda_today = terug_naar_vandaag
    app_klasse._wakesync_agenda_fix_installed = True
    return True
