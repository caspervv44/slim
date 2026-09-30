"""Centrale WakeSync-alarmstate-machine.

De alarmkern is onafhankelijk van Tkinter en netwerkverkeer. Toestandsovergangen
worden pas gecommit nadat de benodigde hardwareacties zijn geslaagd. Als een
speaker- of lampdriver halverwege faalt, probeert WakeSync de hardware terug te
brengen naar de oude toestand en blijft de state-machine retrybaar.

Met ``AlarmRuntimeStore`` kunnen snooze, dismiss en triggerstatus een herstart
overleven. Een gemist alarm wordt alleen binnen ``RECOVERY_WINDOW`` alsnog
gestart; daarna verschijnt een diagnosemelding in plaats van uren later te
gaan rinkelen.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from wekker.alarm.persistence import AlarmRuntimeSnapshot, AlarmRuntimeStore
from wekker.alarm.state import AlarmState
from wekker.clock import Clock
from wekker.hardware.interfaces import Lamp, Speaker
from wekker.settings import Settings

log = logging.getLogger(__name__)

RECOVERY_WINDOW = timedelta(minutes=10)

_ALLOWED: dict[AlarmState, frozenset[AlarmState]] = {
    AlarmState.SLEEPING: frozenset({AlarmState.RINGING}),
    AlarmState.RINGING: frozenset({AlarmState.SNOOZED, AlarmState.DISMISSED}),
    AlarmState.SNOOZED: frozenset({AlarmState.RINGING, AlarmState.DISMISSED}),
    AlarmState.DISMISSED: frozenset({AlarmState.SLEEPING}),
}


class IllegalTransitionError(Exception):
    """Poging tot een niet-toegestane toestandsovergang."""


class AlarmClock:
    """Betrouwbare wekker-core zonder GUI- of netwerkafhankelijkheid."""

    def __init__(
        self,
        settings: Settings,
        clock: Clock,
        speaker: Speaker,
        lamp: Lamp,
        on_state_change: Callable[[AlarmState, AlarmState], None] | None = None,
        runtime_store: AlarmRuntimeStore | None = None,
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._speaker = speaker
        self._lamp = lamp
        self._on_state_change = on_state_change
        self._runtime_store = runtime_store
        self._lock = threading.RLock()

        self.state: AlarmState = AlarmState.SLEEPING
        self.ringing_since: datetime | None = None
        self.snooze_until: datetime | None = None
        self._last_trigger_date: str | None = None
        self._dismissed_date: str | None = None
        self._missed_notice: str = ""
        self._missed_date: str | None = None

        self._restore_runtime_state()

    # -- configuratie ----------------------------------------------------
    def update_settings(self, settings: Settings) -> None:
        with self._lock:
            self._settings = settings

    @property
    def speaker_playing(self) -> bool:
        with self._lock:
            return self._speaker.is_playing

    @property
    def missed_notice(self) -> str:
        with self._lock:
            return self._missed_notice

    def clear_missed_notice(self) -> None:
        with self._lock:
            self._missed_notice = ""
            self._persist_runtime()

    def sound_start(self) -> None:
        with self._lock:
            alarm = self._settings.alarm
            self._speaker.play(alarm.sound, alarm.volume)

    def sound_stop(self) -> None:
        with self._lock:
            self._speaker.stop()

    # -- publieke acties -------------------------------------------------
    def trigger(self) -> bool:
        with self._lock:
            if self.state is not AlarmState.SLEEPING:
                return False
            self._transition(AlarmState.RINGING)
            self._last_trigger_date = self._clock.now().date().isoformat()
            self._persist_runtime()
            return True

    def snooze(self) -> bool:
        """Stel het alarm uit; de eindtijd wordt pas na hardware-success gecommit."""
        with self._lock:
            if self.state is not AlarmState.RINGING:
                return False
            target = self._clock.now() + timedelta(
                minutes=self._settings.alarm.snooze_minutes
            )
            self._transition(AlarmState.SNOOZED, snooze_until=target)
            return True

    def dismiss(self, physical: bool) -> bool:
        """Stop het alarm. Stoppen vereist de fysieke productknop."""
        with self._lock:
            if self.state not in (AlarmState.RINGING, AlarmState.SNOOZED):
                return False
            if not physical:
                log.warning("dismiss geweigerd: geen fysieke bevestiging")
                return False
            self._missed_date = None
            self._transition(AlarmState.DISMISSED)
            return True

    def tick(self) -> AlarmState:
        """Werk de toestand bij. Netwerkverkeer hoort nooit in deze methode."""
        with self._lock:
            now = self._clock.now()
            today = now.date().isoformat()

            # Als een onbetrouwbare systeemklok eerst ná het alarm stond en
            # later (bijvoorbeeld door NTP) terug vóór de echte alarmtijd
            # springt, mag een synthetisch "gemist" alarm niet de rest van de
            # dag blokkeren. Een echte fysieke dismiss wordt nooit gereset.
            if (
                self.state is AlarmState.DISMISSED
                and self._missed_date == today
                and now < self._alarm_trigger_time(now)
            ):
                self._transition(AlarmState.SLEEPING)
                self._last_trigger_date = None
                self._dismissed_date = None
                self._missed_date = None
                self._missed_notice = ""
                self._persist_runtime()

            if self.state is AlarmState.SLEEPING:
                if self._settings.alarm.enabled and self._due_today(now):
                    self._transition(AlarmState.RINGING)
                    self._last_trigger_date = today
                    self._missed_notice = ""
                    self._missed_date = None
                    self._persist_runtime()
                elif self._settings.alarm.enabled:
                    self._mark_missed_when_outside_recovery(now)

            elif self.state is AlarmState.SNOOZED:
                if self.snooze_until is not None and now >= self.snooze_until:
                    # Ook een verlopen snooze krijgt dezelfde begrensde
                    # herstelperiode na een reboot/klokcorrectie.
                    if now <= self.snooze_until + RECOVERY_WINDOW:
                        self._transition(AlarmState.RINGING)
                    else:
                        self._missed_notice = (
                            f"Snooze van {self.snooze_until.strftime('%H:%M')} gemist; "
                            "alarm niet laat opnieuw gestart."
                        )
                        self._missed_date = today
                        self._transition(AlarmState.DISMISSED)
                    self._persist_runtime()

            elif self.state is AlarmState.DISMISSED:
                if self._dismissed_date != today:
                    self._transition(AlarmState.SLEEPING)
                    self._missed_date = None
                    self._missed_notice = ""
                    self._persist_runtime()

            return self.state

    def next_alarm(self, now: datetime | None = None) -> datetime | None:
        with self._lock:
            if not self._settings.alarm.enabled:
                return None
            if self.state is AlarmState.SNOOZED and self.snooze_until is not None:
                return self.snooze_until
            ref = now or self._clock.now()
            uur, minuut = map(int, self._settings.alarm.time.split(":"))
            kandidaat = ref.replace(hour=uur, minute=minuut, second=0, microsecond=0)
            if kandidaat <= ref:
                kandidaat += timedelta(days=1)
            return kandidaat

    def status(self) -> dict:
        with self._lock:
            now = self._clock.now()
            nxt = self.next_alarm(now)
            return {
                "state": self.state.value,
                "now": now.isoformat(),
                "next_alarm": nxt.isoformat() if nxt else None,
                "ringing_since": self.ringing_since.isoformat()
                if self.ringing_since else None,
                "snooze_until": self.snooze_until.isoformat()
                if self.snooze_until else None,
                "missed_notice": self._missed_notice or None,
            }

    # -- herstel/persistentie --------------------------------------------
    def _restore_runtime_state(self) -> None:
        if self._runtime_store is None:
            return
        snapshot = self._runtime_store.load()
        if snapshot is None:
            return

        now = self._clock.now()
        today = now.date().isoformat()
        self._last_trigger_date = snapshot.last_trigger_date
        self._dismissed_date = snapshot.dismissed_date
        self._missed_notice = snapshot.missed_notice
        self._missed_date = snapshot.missed_date

        try:
            ringing_since = (
                datetime.fromisoformat(snapshot.ringing_since)
                if snapshot.ringing_since else None
            )
            snooze_until = (
                datetime.fromisoformat(snapshot.snooze_until)
                if snapshot.snooze_until else None
            )
        except ValueError:
            return

        if snapshot.state == AlarmState.DISMISSED.value and snapshot.dismissed_date == today:
            self.state = AlarmState.DISMISSED
            return

        if snapshot.state == AlarmState.SNOOZED.value and snooze_until is not None:
            if now <= snooze_until + RECOVERY_WINDOW:
                self.state = AlarmState.SNOOZED
                self.snooze_until = snooze_until
                self.ringing_since = ringing_since
                return
            if snooze_until.date().isoformat() == today:
                self.state = AlarmState.DISMISSED
                self._dismissed_date = today
                self._last_trigger_date = today
                self._missed_notice = (
                    f"Snooze van {snooze_until.strftime('%H:%M')} gemist; "
                    "alarm niet laat opnieuw gestart."
                )
                self._missed_date = today
                self._persist_runtime()
                return

        if snapshot.state == AlarmState.RINGING.value and ringing_since is not None:
            age = now - ringing_since
            if timedelta(0) <= age <= RECOVERY_WINDOW:
                # Heractiveer de hardware; de oude triggerdatum blijft behouden.
                self.state = AlarmState.SLEEPING
                try:
                    self._transition(AlarmState.RINGING)
                    self.ringing_since = ringing_since
                    self._last_trigger_date = today
                    self._persist_runtime()
                except Exception:
                    # De normale 1-Hz-lus zal opnieuw proberen via de
                    # herstelvensterlogica; laat init niet crashen.
                    self.state = AlarmState.SLEEPING
                return
            if ringing_since.date().isoformat() == today:
                self.state = AlarmState.DISMISSED
                self._dismissed_date = today
                self._last_trigger_date = today
                self._missed_notice = (
                    f"Alarm van {ringing_since.strftime('%H:%M')} gemist tijdens herstart."
                )
                self._missed_date = today
                self._persist_runtime()
                return

        # Oude/afgelopen toestand hoort niet mee naar een nieuwe dag.
        self.state = AlarmState.SLEEPING
        self.ringing_since = None
        self.snooze_until = None

    def _persist_runtime(self) -> None:
        if self._runtime_store is None:
            return
        snapshot = AlarmRuntimeSnapshot(
            state=self.state.value,
            ringing_since=self.ringing_since.isoformat() if self.ringing_since else None,
            snooze_until=self.snooze_until.isoformat() if self.snooze_until else None,
            last_trigger_date=self._last_trigger_date,
            dismissed_date=self._dismissed_date,
            missed_notice=self._missed_notice,
            missed_date=self._missed_date,
        )
        try:
            self._runtime_store.save(snapshot)
        except Exception:
            # Een SD-kaartfout mag het actieve alarm niet stilleggen. De fout is
            # wel zichtbaar in de logs/diagnose.
            log.exception("persistente alarmstatus kon niet worden opgeslagen")

    # -- intern ----------------------------------------------------------
    def _alarm_trigger_time(self, now: datetime) -> datetime:
        uur, minuut = map(int, self._settings.alarm.time.split(":"))
        return now.replace(hour=uur, minute=minuut, second=0, microsecond=0)

    def _due_today(self, now: datetime) -> bool:
        if self._last_trigger_date == now.date().isoformat():
            return False
        trigger = self._alarm_trigger_time(now)
        return trigger <= now <= trigger + RECOVERY_WINDOW

    def _mark_missed_when_outside_recovery(self, now: datetime) -> None:
        today = now.date().isoformat()
        if self._last_trigger_date == today:
            return
        trigger = self._alarm_trigger_time(now)
        if now <= trigger + RECOVERY_WINDOW:
            return
        self._last_trigger_date = today
        self._dismissed_date = today
        self._missed_date = today
        self._missed_notice = (
            f"Alarm van {trigger.strftime('%H:%M')} gemist; "
            "buiten herstelperiode van 10 minuten."
        )
        self.state = AlarmState.DISMISSED
        self._persist_runtime()

    def _transition(
        self,
        new: AlarmState,
        *,
        snooze_until: datetime | None = None,
    ) -> None:
        if new not in _ALLOWED[self.state]:
            raise IllegalTransitionError(f"{self.state.value} -> {new.value} niet toegestaan")
        old = self.state
        now = self._clock.now()

        try:
            self._apply_hardware_for(new)
        except Exception:
            log.exception(
                "hardwarefout tijdens alarmovergang %s -> %s; oude toestand wordt hersteld",
                old.value,
                new.value,
            )
            try:
                self._apply_hardware_for(old)
            except Exception:
                log.exception("hardware kon niet volledig naar %s worden teruggezet", old.value)
            raise

        # Pas na succesvolle hardwareactie timers en toestand vastleggen.
        if new is AlarmState.RINGING:
            if old is not AlarmState.SNOOZED or self.ringing_since is None:
                self.ringing_since = now
            self.snooze_until = None
        elif new is AlarmState.SNOOZED:
            if snooze_until is None:
                raise ValueError("snooze_until ontbreekt")
            self.snooze_until = snooze_until
        elif new is AlarmState.DISMISSED:
            self._dismissed_date = now.date().isoformat()
            self.snooze_until = None
            self.ringing_since = None
        elif new is AlarmState.SLEEPING:
            self.ringing_since = None
            self.snooze_until = None

        self.state = new
        self._persist_runtime()
        log.info("alarm %s -> %s", old.value, new.value)
        if self._on_state_change:
            try:
                self._on_state_change(old, new)
            except Exception:
                log.exception("on_state_change callback faalde")

    def _apply_hardware_for(self, state: AlarmState) -> None:
        alarm = self._settings.alarm
        lamp_cfg = self._settings.lamp

        if state is AlarmState.RINGING:
            if alarm.speaker_enabled:
                self._speaker.play(alarm.sound, alarm.volume)
            else:
                self._speaker.stop()
            if lamp_cfg.on_with_alarm:
                self._lamp.on(
                    alarm.lamp_brightness,
                    blink=alarm.lamp_blink,
                    pattern=alarm.blink_pattern,
                )
            else:
                self._lamp.off()
            return

        # SNOOZED, DISMISSED en SLEEPING zijn fysiek stil.
        self._speaker.stop()
        self._lamp.off()
