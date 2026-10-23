"""
The dispatch rules, in one place and with no websocket involvement.

Everything here is a plain function over the database so that it can be tested
without a channel layer, and so that the consumers stay thin. The rules it
implements were agreed on 2026-10-13 and are written up in CLAUDE.md; the
load-bearing ones are:

* a subject device transmitting *is* the distress signal,
* the center that owns the nearest free agent is alerted, and only that center,
* a center may only ever dispatch its own agents,
* missions are never created automatically - a human confirms them,
* completion is two phased: the agent reports, then the center closes.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.gis.db.models.functions import Distance
from django.db import IntegrityError, transaction
from django.db.models import Min
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from agents.models import Agent, DistressAlert, Mission
from agents.utils import AlertStatus, MissionOutcome, MissionStatus


class DispatchError(Exception):
    """
    A dispatch rule was violated.

    Carries a short code so a consumer can tell the client what went wrong
    without this module having to know anything about websockets or HTTP.
    """

    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


def _live_cutoff(now=None):
    """
    Agent devices transmit continuously, so one that has gone quiet is offline
    rather than idle, and must not be offered for dispatch.
    """
    return (now or timezone.now()) - timedelta(seconds=settings.AGENT_LIVE_SECONDS)


def agents_by_distance(point, *, region=None, emergency_center=None, now=None):
    """
    Free agents with a live position, nearest first, annotated with `distance`
    in metres.

    Distance is aggregated with Min over the agent's devices: an agent may carry
    more than one device, and without the aggregate they would appear once per
    device, ranked by whichever one the join happened to produce.

    `distance` comes back as a Distance measure object rather than a number, so
    read it as `agent.distance.m` to get metres. Metres rather than degrees
    because the location columns are geography - see LocatableDevice.
    """
    queryset = Agent.objects.filter(busy=False)

    if region is not None:
        queryset = queryset.filter(emergency_center__profile__region=region)
    if emergency_center is not None:
        queryset = queryset.filter(emergency_center=emergency_center)

    return (queryset
            .filter(devices__last_location__isnull=False,
                    devices__last_seen__gte=_live_cutoff(now))
            .annotate(distance=Min(Distance('devices__last_location', point)))
            .order_by('distance'))


def nearest_free_agent(point, region, *, now=None):
    """The nearest free agent anywhere in the region, or None."""
    return agents_by_distance(point, region=region, now=now).first()


def rank_agents_for_center(emergency_center, point, *, now=None):
    """
    The agents this center may actually dispatch, nearest first.

    Scoped to the center's own agents: a center may never dispatch another
    center's agent, so offering them would be misleading.
    """
    return agents_by_distance(point, emergency_center=emergency_center, now=now)


def raise_or_refresh_alert(subject_device, point, *, seen_at=None):
    """
    Record that a subject device is transmitting. Returns (alert, created).

    A device in distress transmits every few seconds, and all of those readings
    belong to one episode, so an open alert is refreshed rather than duplicated.
    The database enforces that with a partial unique constraint; this races with
    itself if two readings arrive together, so a lost race falls back to
    refreshing the row the winner created.
    """
    seen_at = seen_at or timezone.now()

    try:
        with transaction.atomic():
            alert = (DistressAlert.objects
                     .select_for_update()
                     .filter(subject_device=subject_device,
                             status__in=AlertStatus.open_statuses())
                     .first())

            if alert is not None:
                alert.location = point
                alert.last_seen = seen_at
                alert.save(update_fields=['location', 'last_seen', 'updated'])
                return alert, False

            alert = DistressAlert.objects.create(
                subject_device=subject_device,
                location=point,
                first_seen=seen_at,
                last_seen=seen_at,
                status=AlertStatus.UNROUTED,
            )
            return alert, True

    except IntegrityError:
        # Lost the race against a concurrent reading from the same device.
        alert = (DistressAlert.objects
                 .filter(subject_device=subject_device,
                         status__in=AlertStatus.open_statuses())
                 .first())
        if alert is None:
            raise
        alert.location = point
        alert.last_seen = seen_at
        alert.save(update_fields=['location', 'last_seen', 'updated'])
        return alert, False


def route_alert(alert, region, *, now=None):
    """
    Attach an unrouted alert to the center owning the nearest free agent.

    Returns that center, or None when no agent was free anywhere in the region -
    in which case the alert stays UNROUTED and the next reading from the device
    tries again, which is why this needs no scheduler.

    An alert that already has a center is left alone: re-routing it would be
    escalation, which is deliberately out of scope for now.
    """
    if alert.status != AlertStatus.UNROUTED:
        return alert.emergency_center

    agent = nearest_free_agent(alert.location, region, now=now)
    if agent is None:
        return None

    alert.emergency_center = agent.emergency_center
    alert.status = AlertStatus.ROUTED
    alert.save(update_fields=['emergency_center', 'status', 'updated'])
    return alert.emergency_center


def handle_subject_reading(subject_device, point, region, *, seen_at=None, now=None):
    """
    The whole response to one subject reading: raise or refresh the alert, and
    route it if it has nowhere to go yet. Returns (alert, created, center).

    A subject being rescued right now is still trapped, so their device keeps
    transmitting throughout the mission. Those readings must not raise anything:
    the alert they came from is already CONVERTED, so without this check each
    one would raise a fresh alert and tell a center about somebody who is
    already being rescued. Returns (None, False, None) in that case.
    """
    if Mission.objects.filter(subject_device=subject_device,
                              status__in=MissionStatus.open_statuses()).exists():
        return None, False, None

    alert, created = raise_or_refresh_alert(subject_device, point, seen_at=seen_at)
    center = route_alert(alert, region, now=now)
    return alert, created, center


def open_alerts_for_center(emergency_center):
    """
    The possible missions this center still has to decide on.

    An operator who connects after an alert was raised must still see it -
    surviving nobody being logged in is half the reason alerts are rows rather
    than passing messages.
    """
    return (DistressAlert.objects
            .filter(emergency_center=emergency_center,
                    status__in=AlertStatus.open_statuses())
            .select_related('subject_device')
            .order_by('-last_seen'))


def open_missions_for_center(emergency_center):
    """
    The missions this center still has to see through.

    Needed for the same reason as the alert backlog: a mission outlives the
    page it was dispatched from. Without this an operator who reloads, or who
    comes on shift after the dispatch, cannot see the mission at all - and so
    cannot finalise or call it off, which leaves the agent committed and the
    subject unable to raise a new alert.
    """
    return (Mission.objects
            .filter(emergency_center=emergency_center,
                    status__in=MissionStatus.open_statuses())
            .select_related('agent')
            .order_by('created'))


def dismiss_alert(alert, emergency_center):
    """Decline a possible mission. Only the center it was routed to may do so."""
    if alert.emergency_center_id != emergency_center.pk:
        raise DispatchError(_('This alert belongs to another center'), 'not_your_alert')
    if alert.status not in AlertStatus.open_statuses():
        raise DispatchError(_('This alert has already been decided'), 'alert_not_open')

    alert.status = AlertStatus.DISMISSED
    alert.save(update_fields=['status', 'updated'])
    return alert


def create_mission(alert, agent, emergency_center, *, now=None):
    """
    Turn a possible mission into a real one. This is the human decision.

    Locks the agent and the alert so that two operators cannot dispatch the same
    agent, or the same alert, at once. The partial unique constraints are the
    backstop; these checks exist to fail with a usable message rather than an
    IntegrityError.
    """
    with transaction.atomic():
        agent = Agent.objects.select_for_update().get(pk=agent.pk)
        alert = DistressAlert.objects.select_for_update().get(pk=alert.pk)

        if agent.emergency_center_id != emergency_center.pk:
            raise DispatchError(_('This agent belongs to another center'), 'not_your_agent')
        if agent.busy:
            raise DispatchError(_('This agent is already on a mission'), 'agent_busy')
        if alert.emergency_center_id != emergency_center.pk:
            raise DispatchError(_('This alert belongs to another center'), 'not_your_alert')
        if alert.status != AlertStatus.ROUTED:
            raise DispatchError(_('This alert is not awaiting a decision'), 'alert_not_open')

        mission = Mission.objects.create(
            alert=alert,
            agent=agent,
            emergency_center=emergency_center,
            subject_device=alert.subject_device,
            # The device need not be registered to anybody; the person is the
            # optional half of the pair.
            subject=alert.subject_device.subject,
            location=alert.location,
            status=MissionStatus.JUST_DEFINED,
        )

        agent.busy = True
        agent.save(update_fields=['busy', 'updated'])

        alert.status = AlertStatus.CONVERTED
        alert.save(update_fields=['status', 'updated'])

        return mission


def acknowledge_mission(mission, agent, *, now=None):
    """
    The agent's device confirms it has the assignment, which is what starts the
    mission - not its creation.
    """
    with transaction.atomic():
        mission = Mission.objects.select_for_update().get(pk=mission.pk)

        if mission.agent_id != agent.pk:
            raise DispatchError(_('This mission belongs to another agent'), 'not_your_mission')
        if mission.status != MissionStatus.JUST_DEFINED:
            raise DispatchError(_('This mission has already been acknowledged'), 'already_acknowledged')

        mission.status = MissionStatus.IN_PROGRESS
        mission.acknowledged_at = now or timezone.now()
        mission.save(update_fields=['status', 'acknowledged_at', 'updated'])
        return mission


def report_mission(mission, agent, outcome, *, now=None):
    """
    The agent reports how it went. This does not close the mission: the center
    still has to finalise it, and may disagree.
    """
    if outcome not in MissionOutcome.reportable():
        raise DispatchError(_('Unknown outcome'), 'bad_outcome')

    with transaction.atomic():
        mission = Mission.objects.select_for_update().get(pk=mission.pk)

        if mission.agent_id != agent.pk:
            raise DispatchError(_('This mission belongs to another agent'), 'not_your_mission')
        if mission.status != MissionStatus.IN_PROGRESS:
            raise DispatchError(_('This mission is not in progress'), 'not_in_progress')

        mission.status = MissionStatus.REPORTED
        mission.outcome = outcome
        mission.reported_at = now or timezone.now()
        mission.save(update_fields=['status', 'outcome', 'reported_at', 'updated'])
        return mission


def abort_mission(mission, emergency_center, *, now=None):
    """
    The center calls a mission off before the agent has reported.

    Without this an agent is committed for as long as the mission stays open,
    and a mission the agent never acknowledges would hold them for good, since
    nothing times an acknowledgement out.

    The outcome is ABORTED rather than FAILURE: calling a dispatch off is not a
    rescue that failed, and counting it as one would distort what the root panel
    reports.

    The subject is still trapped, so the alert the mission came from goes back
    to UNROUTED instead of staying CONVERTED. The device is still transmitting,
    so the next reading routes it again - to whichever center owns the nearest
    free agent at that point, which may well be a different one.
    """
    with transaction.atomic():
        mission = Mission.objects.select_for_update().get(pk=mission.pk)

        if mission.emergency_center_id != emergency_center.pk:
            raise DispatchError(_('This mission belongs to another center'), 'not_your_mission')
        if mission.status not in (MissionStatus.JUST_DEFINED, MissionStatus.IN_PROGRESS):
            raise DispatchError(
                _('Only a mission the agent has not reported on can be called off'),
                'not_abortable',
            )

        mission.status = MissionStatus.CLOSED
        mission.outcome = MissionOutcome.ABORTED
        mission.closed_at = now or timezone.now()
        mission.save(update_fields=['status', 'outcome', 'closed_at', 'updated'])

        Agent.objects.filter(pk=mission.agent_id).update(busy=False)

        if mission.alert_id is not None:
            DistressAlert.objects.filter(
                pk=mission.alert_id, status=AlertStatus.CONVERTED,
            ).update(status=AlertStatus.UNROUTED, emergency_center=None)

        return mission


def finalize_mission(mission, emergency_center, *, outcome=None, now=None):
    """
    The center closes the mission and releases the agent.

    `outcome` overrides what the agent reported, for the case where the center
    disagrees; left out, the agent's report stands. To call a mission off before
    the agent reports, use abort_mission.
    """
    if outcome is not None and outcome not in MissionOutcome.reportable():
        raise DispatchError(_('Unknown outcome'), 'bad_outcome')

    with transaction.atomic():
        mission = Mission.objects.select_for_update().get(pk=mission.pk)

        if mission.emergency_center_id != emergency_center.pk:
            raise DispatchError(_('This mission belongs to another center'), 'not_your_mission')
        if mission.status != MissionStatus.REPORTED:
            raise DispatchError(_('This mission has not been reported yet'), 'not_reported')

        mission.status = MissionStatus.CLOSED
        mission.closed_at = now or timezone.now()
        if outcome is not None:
            mission.outcome = outcome
        mission.save(update_fields=['status', 'outcome', 'closed_at', 'updated'])

        # Releasing the agent is part of closing the mission, in the same
        # transaction, or Agent.busy drifts away from the mission table.
        Agent.objects.filter(pk=mission.agent_id).update(busy=False)

        return mission
