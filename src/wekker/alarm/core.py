"""Centrale WakeSync-alarmstate-machine.

v10.1 ondersteunt meerdere dagelijkse én datumgebonden alarmprofielen. De kern blijft bewust
onafhankelijk van Tkinter en netwerkverkeer. Per profiel worden trigger-,
dismiss- en gemiststatus apart bijgehouden, zodat het stoppen van een vroeg
alarm een later alarm op dezelfde dag niet blokkeert.
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
from wekker.settings import AlarmProfile, Settings

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
    """Betrouwbare wekker-core met dagelijkse en datumgebonden alarmprofielen."""

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
        self._active_alarm_id: str | None = None
        self._last_trigger_dates: dict[str, str] = {}
        self._dismissed_dates: dict[str, str] = {}
        self._missed_dates: dict[str, str] = {}
        self._missed_notice: str = ""

        # Legacy-attributen blijven bestaan voor oudere tests/diagnosecode.
        self._last_trigger_date: str | None = None
        self._dismissed_date: str | None = None
        self._missed_date: str | None = None

        self._restore_runtime_state()

    # -- configuratie ----------------------------------------------------
    def update_settings(self, settings: Settings) -> None:
        with self._lock:
            self._settings = settings
            ids = {p.id for p in self._profiles()}
            # Een verwijderd alarm mag geen eindeloze stale runtime-info houden.
            self._last_trigger_dates = {
                k: v for k, v in self._last_trigger_dates.items() if k in ids
            }
            self._dismissed_dates = {
                k: v for k, v in self._dismissed_dates.items() if k in ids
            }
            self._missed_dates = {
                k: v for k, v in self._missed_dates.items() if k in ids
            }
            if self._active_alarm_id not in ids:
                self._active_alarm_id = None
                if self.state is not AlarmState.SLEEPING:
                    try:
                        self._transition(AlarmState.SLEEPING)
                    except IllegalTransitionError:
                        self.state = AlarmState.SLEEPING

    def _profiles(self) -> list[AlarmProfile]:
        profiles = list(self._settings.alarm.alarms)
        if not profiles:
            return profiles

        # Backwards compatibility: oudere code/tests wijzigen nog rechtstreeks
        # ``settings.alarm.time`` e.d. na het maken van Settings. Als er maar
        # één profiel is, behandelen we die legacyvelden als live alias van
        # het eerste profiel.
        if len(profiles) == 1:
            primary = profiles[0]
            alarm = self._settings.alarm
            for field in (
                "time", "enabled", "snooze_minutes", "sound", "volume",
                "speaker_enabled", "lamp_brightness", "lamp_blink",
                "blink_pattern", "ramp_up_seconds",
            ):
                value = getattr(alarm, field)
                if getattr(primary, field) != value:
                    setattr(primary, field, value)
            primary.__post_init__()
        return profiles

    def _profile(self, alarm_id: str | None) -> AlarmProfile | None:
        if alarm_id is None:
            return None
        return self._settings.alarm.get(alarm_id)

    def _active_profile(self) -> AlarmProfile:
        profile = self._profile(self._active_alarm_id)
        if profile is not None:
            return profile
        profiles = self._profiles()
        if not profiles:
            raise RuntimeError("Geen alarmprofiel beschikbaar")
        return profiles[0]

    @property
    def active_alarm_id(self) -> str | None:
        with self._lock:
            return self._active_alarm_id

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
            alarm = self._active_profile()
            self._speaker.play(alarm.sound, alarm.volume)

    def sound_stop(self) -> None:
        with self._lock:
            self._speaker.stop()

    # -- publieke acties -------------------------------------------------
    def trigger(self) -> bool:
        """Handmatige trigger: gebruik het eerste ingeschakelde profiel."""
        with self._lock:
            if self.state is not AlarmState.SLEEPING:
                return False
            profile = next((p for p in self._profiles() if p.enabled), None)
            if profile is None:
                return False
            self._active_alarm_id = profile.id
            self._transition(AlarmState.RINGING)
            today = self._clock.now().date().isoformat()
            self._last_trigger_dates[profile.id] = today
            self._sync_legacy_dates(profile.id)
            self._persist_runtime()
            return True

    def snooze(self) -> bool:
        with self._lock:
            if self.state is not AlarmState.RINGING:
                return False
            profile = self._active_profile()
            target = self._clock.now() + timedelta(minutes=profile.snooze_minutes)
            self._transition(AlarmState.SNOOZED, snooze_until=target)
            return True

    def dismiss(self, physical: bool) -> bool:
        """Stop het actieve alarm. Stoppen vereist de fysieke productknop."""
        with self._lock:
            if self.state not in (AlarmState.RINGING, AlarmState.SNOOZED):
                return False
            if not physical:
                log.warning("dismiss geweigerd: geen fysieke bevestiging")
                return False
            alarm_id = self._active_profile().id
            self._missed_dates.pop(alarm_id, None)
            self._transition(AlarmState.DISMISSED)
            return True

    def tick(self) -> AlarmState:
        """Werk de toestand bij. Netwerkverkeer hoort nooit in deze methode."""
        with self._lock:
            now = self._clock.now()
            today = now.date().isoformat()

            self._repair_backward_clock(now)

            if self.state is AlarmState.SLEEPING:
                due = self._find_due_profile(now)
                if due is not None:
                    self._active_alarm_id = due.id
                    self._transition(AlarmState.RINGING)
                    self._last_trigger_dates[due.id] = today
                    self._missed_dates.pop(due.id, None)
                    self._missed_notice = ""
                    self._sync_legacy_dates(due.id)
                    self._persist_runtime()
                else:
                    self._mark_missed_profiles(now)

            elif self.state is AlarmState.SNOOZED:
                if self.snooze_until is not None and now >= self.snooze_until:
                    alarm_id = self._active_profile().id
                    if now <= self.snooze_until + RECOVERY_WINDOW:
                        self._transition(AlarmState.RINGING)
                    else:
                        self._missed_notice = (
                            f"Snooze van {self.snooze_until.strftime('%H:%M')} gemist; "
                            "alarm niet laat opnieuw gestart."
                        )
                        self._missed_dates[alarm_id] = today
                        self._transition(AlarmState.DISMISSED)
                    self._sync_legacy_dates(alarm_id)
                    self._persist_runtime()

            elif self.state is AlarmState.DISMISSED:
                active_id = self._active_alarm_id
                # Bij één alarm blijft DISMISSED tot de volgende dag zoals
                # oudere WakeSync-versies. Met meerdere alarmen gaan we terug
                # naar SLEEPING zodra er later vandaag nog een alarm kan komen.
                if (
                    active_id is None
                    or self._dismissed_dates.get(active_id) != today
                    or self._has_future_other_alarm(now, active_id)
                ):
                    self._transition(AlarmState.SLEEPING)
                    self._active_alarm_id = None
                    self._persist_runtime()

            return self.state

    def next_alarm(self, now: datetime | None = None) -> datetime | None:
        with self._lock:
            if self.state is AlarmState.SNOOZED and self.snooze_until is not None:
                return self.snooze_until
            ref = now or self._clock.now()
            today = ref.date().isoformat()
            candidates: list[datetime] = []
            for profile in self._profiles():
                if not profile.enabled:
                    continue

                scheduled = self._trigger_time(ref, profile)

                # Datumgebonden alarmen zijn eenmalig. Ze worden nooit stilzwijgend
                # naar "morgen" doorgeschoven nadat de gekozen datum voorbij is.
                if profile.date:
                    done = (
                        self._last_trigger_dates.get(profile.id) == profile.date
                        or self._dismissed_dates.get(profile.id) == profile.date
                        or self._missed_dates.get(profile.id) == profile.date
                    )
                    if not done and scheduled > ref:
                        candidates.append(scheduled)
                    elif not done and scheduled <= ref <= scheduled + RECOVERY_WINDOW:
                        candidates.append(scheduled)
                    continue

                already_done = (
                    self._last_trigger_dates.get(profile.id) == today
                    or self._dismissed_dates.get(profile.id) == today
                    or self._missed_dates.get(profile.id) == today
                )
                if scheduled > ref and not already_done:
                    candidates.append(scheduled)
                else:
                    candidates.append(scheduled + timedelta(days=1))
            return min(candidates) if candidates else None

    def status(self) -> dict:
        with self._lock:
            now = self._clock.now()
            nxt = self.next_alarm(now)
            return {
                "state": self.state.value,
                "active_alarm_id": self._active_alarm_id,
                "now": now.isoformat(),
                "next_alarm": nxt.isoformat() if nxt else None,
                "ringing_since": self.ringing_since.isoformat()
                if self.ringing_since else None,
                "snooze_until": self.snooze_until.isoformat()
                if self.snooze_until else None,
                "missed_notice": self._missed_notice or None,
            }

    # -- selectie / planning --------------------------------------------
    def _trigger_time(self, now: datetime, profile: AlarmProfile) -> datetime:
        """Geef de geplande datetime in dezelfde tijdzone als ``now``."""
        hour, minute = map(int, profile.time.split(":"))
        if profile.date:
            year, month, day = map(int, profile.date.split("-"))
            return now.replace(
                year=year,
                month=month,
                day=day,
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
            )
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    @staticmethod
    def _runs_on_day(profile: AlarmProfile, day_iso: str) -> bool:
        """Dagelijkse alarmen lopen elke dag; datumalarmen alleen op hun datum."""
        return profile.date is None or profile.date == day_iso

    def _find_due_profile(self, now: datetime) -> AlarmProfile | None:
        today = now.date().isoformat()
        candidates: list[tuple[datetime, AlarmProfile]] = []
        for profile in self._profiles():
            if not profile.enabled:
                continue
            if not self._runs_on_day(profile, today):
                continue
            if self._last_trigger_dates.get(profile.id) == today:
                continue
            if self._dismissed_dates.get(profile.id) == today:
                continue
            trigger = self._trigger_time(now, profile)
            if trigger <= now <= trigger + RECOVERY_WINDOW:
                candidates.append((trigger, profile))
        candidates.sort(key=lambda pair: (pair[0], pair[1].id))
        return candidates[0][1] if candidates else None

    def _has_future_other_alarm(self, now: datetime, active_id: str) -> bool:
        today = now.date().isoformat()
        for profile in self._profiles():
            if profile.id == active_id or not profile.enabled:
                continue
            if not self._runs_on_day(profile, today):
                continue
            if self._last_trigger_dates.get(profile.id) == today:
                continue
            if self._dismissed_dates.get(profile.id) == today:
                continue
            if self._missed_dates.get(profile.id) == today:
                continue
            if self._trigger_time(now, profile) > now:
                return True
        return False

    def _mark_missed_profiles(self, now: datetime) -> None:
        today = now.date().isoformat()
        missed_now: list[tuple[datetime, AlarmProfile]] = []
        for profile in self._profiles():
            if not profile.enabled:
                continue
            if not self._runs_on_day(profile, today):
                continue
            if self._last_trigger_dates.get(profile.id) == today:
                continue
            if self._dismissed_dates.get(profile.id) == today:
                continue
            trigger = self._trigger_time(now, profile)
            if now > trigger + RECOVERY_WINDOW:
                self._last_trigger_dates[profile.id] = today
                self._dismissed_dates[profile.id] = today
                self._missed_dates[profile.id] = today
                missed_now.append((trigger, profile))

        if not missed_now:
            return

        trigger, profile = sorted(missed_now, key=lambda x: x[0])[-1]
        self._missed_notice = (
            f"Alarm van {trigger.strftime('%H:%M')} gemist; "
            "buiten herstelperiode van 10 minuten."
        )
        self._active_alarm_id = profile.id
        self._sync_legacy_dates(profile.id)

        # Voor compatibiliteit blijft een enkele afgelopen wekker DISMISSED.
        # Met een later alarm blijven we SLEEPING zodat dat alarm nog kan afgaan.
        if not self._has_future_other_alarm(now, profile.id):
            self.state = AlarmState.DISMISSED
        self._persist_runtime()

    def _repair_backward_clock(self, now: datetime) -> None:
        """Maak alleen synthetisch gemiste alarmen opnieuw beschikbaar.

        Een fysieke dismiss blijft staan. Dit beschermt tegen een klok die bij
        boot te ver vooruit stond en later door NTP/RTC wordt gecorrigeerd.
        """
        today = now.date().isoformat()
        for profile in self._profiles():
            if not self._runs_on_day(profile, today):
                continue
            if self._missed_dates.get(profile.id) != today:
                continue
            if now < self._trigger_time(now, profile):
                self._missed_dates.pop(profile.id, None)
                self._last_trigger_dates.pop(profile.id, None)
                self._dismissed_dates.pop(profile.id, None)
                if self._active_alarm_id == profile.id and self.state is AlarmState.DISMISSED:
                    self.state = AlarmState.SLEEPING
                    self._active_alarm_id = None
                self._missed_notice = ""
                self._persist_runtime()

    # -- herstel/persistentie --------------------------------------------
    def _restore_runtime_state(self) -> None:
        if self._runtime_store is None:
            return
        snapshot = self._runtime_store.load()
        if snapshot is None:
            return

        profiles = self._profiles()
        if not profiles:
            return
        primary_id = profiles[0].id
        ids = {p.id for p in profiles}
        now = self._clock.now()
        today = now.date().isoformat()

        self._last_trigger_dates = dict(snapshot.last_trigger_dates or {})
        self._dismissed_dates = dict(snapshot.dismissed_dates or {})
        self._missed_dates = dict(snapshot.missed_dates or {})

        # Migratie van schema 1/2 naar het eerste v10-profiel.
        if not self._last_trigger_dates and snapshot.last_trigger_date:
            self._last_trigger_dates[primary_id] = snapshot.last_trigger_date
        if not self._dismissed_dates and snapshot.dismissed_date:
            self._dismissed_dates[primary_id] = snapshot.dismissed_date
        if not self._missed_dates and snapshot.missed_date:
            self._missed_dates[primary_id] = snapshot.missed_date

        self._last_trigger_dates = {k: v for k, v in self._last_trigger_dates.items() if k in ids}
        self._dismissed_dates = {k: v for k, v in self._dismissed_dates.items() if k in ids}
        self._missed_dates = {k: v for k, v in self._missed_dates.items() if k in ids}
        self._missed_notice = snapshot.missed_notice
        self._active_alarm_id = (
            snapshot.active_alarm_id if snapshot.active_alarm_id in ids else primary_id
        )

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

        active_id = self._active_alarm_id or primary_id

        if snapshot.state == AlarmState.DISMISSED.value:
            if self._dismissed_dates.get(active_id) == today:
                self.state = AlarmState.DISMISSED
                self._sync_legacy_dates(active_id)
                return

        if snapshot.state == AlarmState.SNOOZED.value and snooze_until is not None:
            if now <= snooze_until + RECOVERY_WINDOW:
                self.state = AlarmState.SNOOZED
                self.snooze_until = snooze_until
                self.ringing_since = ringing_since
                self._sync_legacy_dates(active_id)
                return
            if snooze_until.date().isoformat() == today:
                self.state = AlarmState.DISMISSED
                self._dismissed_dates[active_id] = today
                self._last_trigger_dates[active_id] = today
                self._missed_dates[active_id] = today
                self._missed_notice = (
                    f"Snooze van {snooze_until.strftime('%H:%M')} gemist; "
                    "alarm niet laat opnieuw gestart."
                )
                self._sync_legacy_dates(active_id)
                self._persist_runtime()
                return

        if snapshot.state == AlarmState.RINGING.value and ringing_since is not None:
            age = now - ringing_since
            if timedelta(0) <= age <= RECOVERY_WINDOW:
                self.state = AlarmState.SLEEPING
                try:
                    self._transition(AlarmState.RINGING)
                    self.ringing_since = ringing_since
                    self._last_trigger_dates[active_id] = today
                    self._sync_legacy_dates(active_id)
                    self._persist_runtime()
                except Exception:
                    self.state = AlarmState.SLEEPING
                return
            if ringing_since.date().isoformat() == today:
                self.state = AlarmState.DISMISSED
                self._dismissed_dates[active_id] = today
                self._last_trigger_dates[active_id] = today
                self._missed_dates[active_id] = today
                self._missed_notice = (
                    f"Alarm van {ringing_since.strftime('%H:%M')} gemist tijdens herstart."
                )
                self._sync_legacy_dates(active_id)
                self._persist_runtime()
                return

        self.state = AlarmState.SLEEPING
        self.ringing_since = None
        self.snooze_until = None
        self._active_alarm_id = None

    def _sync_legacy_dates(self, alarm_id: str | None) -> None:
        if alarm_id is None:
            self._last_trigger_date = None
            self._dismissed_date = None
            self._missed_date = None
            return
        self._last_trigger_date = self._last_trigger_dates.get(alarm_id)
        self._dismissed_date = self._dismissed_dates.get(alarm_id)
        self._missed_date = self._missed_dates.get(alarm_id)

    def _persist_runtime(self) -> None:
        if self._runtime_store is None:
            return
        self._sync_legacy_dates(self._active_alarm_id)
        snapshot = AlarmRuntimeSnapshot(
            state=self.state.value,
            ringing_since=self.ringing_since.isoformat() if self.ringing_since else None,
            snooze_until=self.snooze_until.isoformat() if self.snooze_until else None,
            last_trigger_date=self._last_trigger_date,
            dismissed_date=self._dismissed_date,
            missed_notice=self._missed_notice,
            missed_date=self._missed_date,
            active_alarm_id=self._active_alarm_id,
            last_trigger_dates=self._last_trigger_dates,
            dismissed_dates=self._dismissed_dates,
            missed_dates=self._missed_dates,
        )
        try:
            self._runtime_store.save(snapshot)
        except Exception:
            log.exception("persistente alarmstatus kon niet worden opgeslagen")

    # -- state-machine ---------------------------------------------------
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

        if new is AlarmState.RINGING:
            if old is not AlarmState.SNOOZED or self.ringing_since is None:
                self.ringing_since = now
            self.snooze_until = None
        elif new is AlarmState.SNOOZED:
            if snooze_until is None:
                raise ValueError("snooze_until ontbreekt")
            self.snooze_until = snooze_until
        elif new is AlarmState.DISMISSED:
            alarm_id = self._active_profile().id
            self._dismissed_dates[alarm_id] = now.date().isoformat()
            self.snooze_until = None
            self.ringing_since = None
        elif new is AlarmState.SLEEPING:
            self.ringing_since = None
            self.snooze_until = None

        self.state = new
        self._sync_legacy_dates(self._active_alarm_id)
        self._persist_runtime()
        log.info(
            "alarm %s -> %s (%s)",
            old.value,
            new.value,
            self._active_alarm_id or "geen profiel",
        )
        if self._on_state_change:
            try:
                self._on_state_change(old, new)
            except Exception:
                log.exception("on_state_change callback faalde")

    def _apply_hardware_for(self, state: AlarmState) -> None:
        alarm = self._active_profile()
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

        self._speaker.stop()
        self._lamp.off()
