"""
Tests for the dispatch rules in agents.services.

These run against a real PostGIS test database but never touch a channel layer,
so they are fast and they exercise the rules rather than the plumbing.
"""
import asyncio
import datetime
import time
from datetime import timedelta
from unittest.mock import patch

import jwt
from asgiref.sync import sync_to_async
from channels.auth import AuthMiddlewareStack
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point, Polygon
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from agents import services
from agents.consumers import queue_name_for
from agents.models import (
    Agent, AgentDevice, AgentRecords, DistressAlert, Mission, Region, SubjectDevice,
)
from agents.utils import AlertStatus, MissionOutcome, MissionStatus, ModelType
from profiles.models import Profile
from profiles.utils import ProfileType
from resc.utils import all_websocket_urlpatterns

User = get_user_model()

# Bologna. One degree of latitude is about 111 km, so these offsets give
# predictable distances to assert against.
ORIGIN = Point(11.3426, 44.4949, srid=4326)


def north_of(origin, metres):
    return Point(origin.x, origin.y + metres / 111_320, srid=4326)


class DispatchTestCase(TestCase):
    """
    One region, two centers with two agents each, and a subject in distress.

    Centre A's agents sit 500 m and 4 km from the subject; centre B's sit 2 km
    and 6 km. So the nearest agent overall belongs to centre A.
    """

    def setUp(self):
        self.region = Region.objects.create(
            name='Bologna',
            description='test region',
            polygon=Polygon.from_bbox((11.0, 44.2, 11.7, 44.8)),
        )
        self.now = timezone.now()

        self.centre_a = self._make_centre('a@resc.com')
        self.centre_b = self._make_centre('b@resc.com')

        self.a_near = self._make_agent(self.centre_a, 'a-near', 500)
        self.a_far = self._make_agent(self.centre_a, 'a-far', 4_000)
        self.b_mid = self._make_agent(self.centre_b, 'b-mid', 2_000)
        self.b_far = self._make_agent(self.centre_b, 'b-far', 6_000)

        self.subject = User.objects.create_user(
            email='victim@resc.com', firstname='V', lastname='Ictim', password='x',
        )
        Profile.objects.filter(user=self.subject).update(
            type=ProfileType.NORMAL, region=self.region,
        )
        self.subject_device = SubjectDevice.objects.create(
            name='victim-device', subject=self.subject,
        )

    def _make_centre(self, email):
        user = User.objects.create_user(
            email=email, firstname='C', lastname='Entre', password='x',
        )
        # A profile is created by signal; point it at our region.
        Profile.objects.filter(user=user).update(
            type=ProfileType.EMERGENCY_CENTER, region=self.region,
        )
        return user

    def _make_agent(self, centre, name, metres_away, *, seen_ago=0):
        agent = Agent.objects.create(name=name, emergency_center=centre)
        AgentDevice.objects.create(
            agent=agent,
            name=f'{name}-device',
            last_location=north_of(ORIGIN, metres_away),
            last_seen=self.now - timedelta(seconds=seen_ago),
        )
        return agent

    def raise_alert(self):
        alert, created, centre = services.handle_subject_reading(
            self.subject_device, ORIGIN, self.region, now=self.now,
        )
        return alert, created, centre


class NearestAgentTests(DispatchTestCase):

    def test_distance_is_in_metres(self):
        """
        The geography column decision: metres, not degrees. At plain 4326
        geometry these would read about 0.0045 and 0.018.
        """
        agents = list(services.agents_by_distance(ORIGIN, region=self.region, now=self.now))
        self.assertAlmostEqual(agents[0].distance.m, 500, delta=10)
        self.assertAlmostEqual(agents[1].distance.m, 2_000, delta=20)

    def test_orders_nearest_first_across_centers(self):
        agents = list(services.agents_by_distance(ORIGIN, region=self.region, now=self.now))
        self.assertEqual(
            [a.name for a in agents],
            ['a-near', 'b-mid', 'a-far', 'b-far'],
        )

    def test_busy_agents_are_excluded(self):
        Agent.objects.filter(pk=self.a_near.pk).update(busy=True)
        self.assertEqual(
            services.nearest_free_agent(ORIGIN, self.region, now=self.now).name,
            'b-mid',
        )

    def test_agents_that_have_gone_quiet_are_excluded(self):
        """A silent agent device is offline, not idle."""
        AgentDevice.objects.filter(agent=self.a_near).update(
            last_seen=self.now - timedelta(seconds=600),
        )
        self.assertEqual(
            services.nearest_free_agent(ORIGIN, self.region, now=self.now).name,
            'b-mid',
        )

    def test_agents_with_no_position_are_excluded(self):
        AgentDevice.objects.filter(agent=self.a_near).update(last_location=None)
        self.assertEqual(
            services.nearest_free_agent(ORIGIN, self.region, now=self.now).name,
            'b-mid',
        )

    def test_agent_with_two_devices_appears_once(self):
        """Without the Min aggregate an agent would appear once per device."""
        AgentDevice.objects.create(
            agent=self.a_near, name='second-device',
            last_location=north_of(ORIGIN, 300), last_seen=self.now,
        )
        agents = list(services.agents_by_distance(ORIGIN, region=self.region, now=self.now))
        self.assertEqual([a.name for a in agents].count('a-near'), 1)
        # ...and it is ranked by its closest device.
        self.assertAlmostEqual(agents[0].distance.m, 300, delta=10)

    def test_ranking_for_a_center_shows_only_its_own_agents(self):
        ranked = services.rank_agents_for_center(self.centre_a, ORIGIN, now=self.now)
        self.assertEqual([a.name for a in ranked], ['a-near', 'a-far'])


class AlertTests(DispatchTestCase):

    def test_first_reading_raises_an_alert(self):
        alert, created, centre = self.raise_alert()
        self.assertTrue(created)
        self.assertEqual(alert.status, AlertStatus.ROUTED)
        self.assertEqual(DistressAlert.objects.count(), 1)

    def test_alert_goes_to_the_owner_of_the_nearest_agent(self):
        """Centre A owns the 500 m agent, so centre A is alerted - only it."""
        _, _, centre = self.raise_alert()
        self.assertEqual(centre, self.centre_a)

    def test_alert_follows_the_agent_not_the_center(self):
        """
        Make centre B own the nearest agent and the alert must move to B, even
        though nothing about the centers themselves changed.
        """
        Agent.objects.filter(pk=self.a_near.pk).update(emergency_center=self.centre_b)
        _, _, centre = self.raise_alert()
        self.assertEqual(centre, self.centre_b)

    def test_later_readings_refresh_rather_than_duplicate(self):
        """A device in distress transmits every few seconds."""
        first, created, _ = self.raise_alert()
        self.assertTrue(created)

        later = self.now + timedelta(seconds=3)
        moved = north_of(ORIGIN, 25)
        alert, created, _ = services.handle_subject_reading(
            self.subject_device, moved, self.region, seen_at=later, now=self.now,
        )

        self.assertFalse(created)
        self.assertEqual(alert.pk, first.pk)
        self.assertEqual(DistressAlert.objects.count(), 1)
        self.assertEqual(alert.last_seen, later)
        self.assertAlmostEqual(alert.location.y, moved.y, places=5)
        # first_seen must not move - it is when the episode began.
        self.assertEqual(alert.first_seen, first.first_seen)

    def test_unrouted_when_no_agent_is_free_and_retried_later(self):
        """This is why unrouted alerts need no scheduler."""
        Agent.objects.update(busy=True)

        alert, _, centre = self.raise_alert()
        self.assertIsNone(centre)
        self.assertEqual(alert.status, AlertStatus.UNROUTED)

        Agent.objects.filter(pk=self.a_near.pk).update(busy=False)
        alert, created, centre = self.raise_alert()

        self.assertFalse(created)
        self.assertEqual(centre, self.centre_a)
        self.assertEqual(alert.status, AlertStatus.ROUTED)

    def test_a_routed_alert_is_not_rerouted(self):
        """Re-routing would be escalation, which is deliberately out of scope."""
        alert, _, _ = self.raise_alert()
        Agent.objects.filter(pk=self.a_near.pk).update(emergency_center=self.centre_b)

        centre = services.route_alert(alert, self.region, now=self.now)
        self.assertEqual(centre, self.centre_a)

    def test_a_decided_alert_lets_a_new_episode_start(self):
        alert, _, _ = self.raise_alert()
        services.dismiss_alert(alert, self.centre_a)

        alert2, created, _ = self.raise_alert()
        self.assertTrue(created)
        self.assertNotEqual(alert2.pk, alert.pk)

    def test_another_center_cannot_dismiss_the_alert(self):
        alert, _, _ = self.raise_alert()
        with self.assertRaises(services.DispatchError) as caught:
            services.dismiss_alert(alert, self.centre_b)
        self.assertEqual(caught.exception.code, 'not_your_alert')


class MissionCreationTests(DispatchTestCase):

    def setUp(self):
        super().setUp()
        self.alert, _, _ = self.raise_alert()

    def test_center_creates_a_mission_from_its_own_agent(self):
        mission = services.create_mission(self.alert, self.a_near, self.centre_a)

        self.assertEqual(mission.status, MissionStatus.JUST_DEFINED)
        self.assertEqual(mission.subject_device, self.subject_device)
        self.assertEqual(mission.subject, self.subject)
        self.assertEqual(mission.emergency_center, self.centre_a)
        # The location is a snapshot of where the subject was, not the subject's
        # home address.
        self.assertAlmostEqual(mission.location.y, ORIGIN.y, places=5)

    def test_creating_a_mission_marks_the_agent_busy_and_converts_the_alert(self):
        services.create_mission(self.alert, self.a_near, self.centre_a)

        self.a_near.refresh_from_db()
        self.alert.refresh_from_db()
        self.assertTrue(self.a_near.busy)
        self.assertEqual(self.alert.status, AlertStatus.CONVERTED)

    def test_a_center_cannot_dispatch_another_centers_agent(self):
        """Rule 3, and the reason the dispatch roster is scoped per center."""
        with self.assertRaises(services.DispatchError) as caught:
            services.create_mission(self.alert, self.b_mid, self.centre_a)
        self.assertEqual(caught.exception.code, 'not_your_agent')
        self.assertEqual(Mission.objects.count(), 0)

    def test_a_center_cannot_act_on_someone_elses_alert(self):
        with self.assertRaises(services.DispatchError) as caught:
            services.create_mission(self.alert, self.b_mid, self.centre_b)
        self.assertEqual(caught.exception.code, 'not_your_alert')

    def test_a_busy_agent_cannot_be_dispatched(self):
        Agent.objects.filter(pk=self.a_near.pk).update(busy=True)
        with self.assertRaises(services.DispatchError) as caught:
            services.create_mission(self.alert, self.a_near, self.centre_a)
        self.assertEqual(caught.exception.code, 'agent_busy')

    def test_an_alert_cannot_be_dispatched_twice(self):
        services.create_mission(self.alert, self.a_near, self.centre_a)
        with self.assertRaises(services.DispatchError) as caught:
            services.create_mission(self.alert, self.a_far, self.centre_a)
        self.assertEqual(caught.exception.code, 'alert_not_open')
        self.assertEqual(Mission.objects.count(), 1)

    def test_a_subject_with_no_account_still_gets_a_mission(self):
        """SubjectDevice.subject is nullable, which is why the device is the key."""
        SubjectDevice.objects.filter(pk=self.subject_device.pk).update(subject=None)
        self.subject_device.refresh_from_db()

        mission = services.create_mission(self.alert, self.a_near, self.centre_a)
        self.assertIsNone(mission.subject)
        self.assertEqual(mission.subject_device, self.subject_device)


class MissionLifecycleTests(DispatchTestCase):

    def setUp(self):
        super().setUp()
        alert, _, _ = self.raise_alert()
        self.mission = services.create_mission(alert, self.a_near, self.centre_a)

    def test_acknowledgement_starts_the_mission(self):
        """Rule 6: the device acknowledging is what starts it, not creation."""
        mission = services.acknowledge_mission(self.mission, self.a_near)
        self.assertEqual(mission.status, MissionStatus.IN_PROGRESS)
        self.assertIsNotNone(mission.acknowledged_at)

    def test_another_agent_cannot_acknowledge(self):
        with self.assertRaises(services.DispatchError) as caught:
            services.acknowledge_mission(self.mission, self.b_mid)
        self.assertEqual(caught.exception.code, 'not_your_mission')

    def test_cannot_acknowledge_twice(self):
        services.acknowledge_mission(self.mission, self.a_near)
        with self.assertRaises(services.DispatchError) as caught:
            services.acknowledge_mission(self.mission, self.a_near)
        self.assertEqual(caught.exception.code, 'already_acknowledged')

    def test_cannot_report_before_acknowledging(self):
        with self.assertRaises(services.DispatchError) as caught:
            services.report_mission(self.mission, self.a_near, MissionOutcome.SUCCESS)
        self.assertEqual(caught.exception.code, 'not_in_progress')

    def test_reporting_does_not_close_the_mission(self):
        """Completion is two phased - the center still has to finalise."""
        services.acknowledge_mission(self.mission, self.a_near)
        mission = services.report_mission(self.mission, self.a_near, MissionOutcome.SUCCESS)

        self.assertEqual(mission.status, MissionStatus.REPORTED)
        self.assertEqual(mission.outcome, MissionOutcome.SUCCESS)
        self.assertIsNotNone(mission.reported_at)

        self.a_near.refresh_from_db()
        self.assertTrue(self.a_near.busy, 'agent is still committed until the center closes it')

    def test_finalising_closes_it_and_releases_the_agent(self):
        services.acknowledge_mission(self.mission, self.a_near)
        services.report_mission(self.mission, self.a_near, MissionOutcome.SUCCESS)
        mission = services.finalize_mission(self.mission, self.centre_a)

        self.assertEqual(mission.status, MissionStatus.CLOSED)
        self.assertEqual(mission.outcome, MissionOutcome.SUCCESS)
        self.assertIsNotNone(mission.closed_at)

        self.a_near.refresh_from_db()
        self.assertFalse(self.a_near.busy)

    def test_the_center_may_overrule_the_agents_report(self):
        services.acknowledge_mission(self.mission, self.a_near)
        services.report_mission(self.mission, self.a_near, MissionOutcome.SUCCESS)
        mission = services.finalize_mission(
            self.mission, self.centre_a, outcome=MissionOutcome.FAILURE,
        )
        self.assertEqual(mission.outcome, MissionOutcome.FAILURE)

    def test_cannot_finalise_before_the_agent_reports(self):
        services.acknowledge_mission(self.mission, self.a_near)
        with self.assertRaises(services.DispatchError) as caught:
            services.finalize_mission(self.mission, self.centre_a)
        self.assertEqual(caught.exception.code, 'not_reported')

    def test_another_center_cannot_finalise(self):
        services.acknowledge_mission(self.mission, self.a_near)
        services.report_mission(self.mission, self.a_near, MissionOutcome.SUCCESS)
        with self.assertRaises(services.DispatchError) as caught:
            services.finalize_mission(self.mission, self.centre_b)
        self.assertEqual(caught.exception.code, 'not_your_mission')

    def test_a_rubbish_outcome_is_rejected(self):
        services.acknowledge_mission(self.mission, self.a_near)
        with self.assertRaises(services.DispatchError) as caught:
            services.report_mission(self.mission, self.a_near, 99)
        self.assertEqual(caught.exception.code, 'bad_outcome')

    def test_a_reading_during_a_mission_does_not_raise_another_alert(self):
        """
        The subject is still trapped while being rescued, so their device keeps
        transmitting. Those readings must not tell a center about somebody who
        is already being rescued.
        """
        before = DistressAlert.objects.count()

        alert, created, centre = services.handle_subject_reading(
            self.subject_device, ORIGIN, self.region, now=self.now,
        )

        self.assertIsNone(alert)
        self.assertFalse(created)
        self.assertIsNone(centre)
        self.assertEqual(DistressAlert.objects.count(), before)

    def test_center_can_abort_a_mission_the_agent_never_acknowledged(self):
        """The case that would otherwise hold an agent busy for good."""
        mission = services.abort_mission(self.mission, self.centre_a)

        self.assertEqual(mission.status, MissionStatus.CLOSED)
        self.assertEqual(mission.outcome, MissionOutcome.ABORTED)
        self.assertIsNotNone(mission.closed_at)

        self.a_near.refresh_from_db()
        self.assertFalse(self.a_near.busy)

    def test_center_can_abort_a_mission_already_under_way(self):
        services.acknowledge_mission(self.mission, self.a_near)
        mission = services.abort_mission(self.mission, self.centre_a)

        self.assertEqual(mission.status, MissionStatus.CLOSED)
        self.a_near.refresh_from_db()
        self.assertFalse(self.a_near.busy)

    def test_aborting_does_not_abandon_the_subject(self):
        """
        The alert goes back to unrouted, so the next reading from the still
        transmitting device routes it again - possibly to another center.
        """
        services.abort_mission(self.mission, self.centre_a)

        self.mission.alert.refresh_from_db()
        self.assertEqual(self.mission.alert.status, AlertStatus.UNROUTED)
        self.assertIsNone(self.mission.alert.emergency_center)

        alert, created, centre = services.handle_subject_reading(
            self.subject_device, ORIGIN, self.region, now=self.now,
        )
        self.assertFalse(created, 'the same alert is reused, not a new one')
        self.assertEqual(alert.pk, self.mission.alert.pk)
        self.assertEqual(centre, self.centre_a)

    def test_aborting_can_hand_the_subject_to_a_different_center(self):
        services.abort_mission(self.mission, self.centre_a)
        # Centre A's agents are now the far ones; B's 2 km agent is nearest.
        Agent.objects.filter(pk=self.a_near.pk).update(busy=True)

        _, _, centre = services.handle_subject_reading(
            self.subject_device, ORIGIN, self.region, now=self.now,
        )
        self.assertEqual(centre, self.centre_b)

    def test_another_center_cannot_abort(self):
        with self.assertRaises(services.DispatchError) as caught:
            services.abort_mission(self.mission, self.centre_b)
        self.assertEqual(caught.exception.code, 'not_your_mission')

    def test_cannot_abort_once_the_agent_has_reported(self):
        """After a report it is finalise, not abort - the work was done."""
        services.acknowledge_mission(self.mission, self.a_near)
        services.report_mission(self.mission, self.a_near, MissionOutcome.SUCCESS)

        with self.assertRaises(services.DispatchError) as caught:
            services.abort_mission(self.mission, self.centre_a)
        self.assertEqual(caught.exception.code, 'not_abortable')

    def test_an_agent_cannot_report_aborted(self):
        """Calling a mission off is the center's decision, not the agent's."""
        services.acknowledge_mission(self.mission, self.a_near)

        with self.assertRaises(services.DispatchError) as caught:
            services.report_mission(self.mission, self.a_near, MissionOutcome.ABORTED)
        self.assertEqual(caught.exception.code, 'bad_outcome')

    def test_an_aborted_agent_can_be_dispatched_again(self):
        services.abort_mission(self.mission, self.centre_a)

        alert, _, _ = services.handle_subject_reading(
            self.subject_device, ORIGIN, self.region, now=self.now,
        )
        mission = services.create_mission(alert, self.a_near, self.centre_a)
        self.assertEqual(mission.status, MissionStatus.JUST_DEFINED)

    def test_closing_a_mission_frees_the_agent_for_the_next_one(self):
        """The whole cycle, end to end."""
        services.acknowledge_mission(self.mission, self.a_near)
        services.report_mission(self.mission, self.a_near, MissionOutcome.SUCCESS)
        services.finalize_mission(self.mission, self.centre_a)

        second_device = SubjectDevice.objects.create(name='another', subject=None)
        alert, _, centre = services.handle_subject_reading(
            second_device, ORIGIN, self.region, now=self.now,
        )
        self.assertEqual(centre, self.centre_a)

        mission = services.create_mission(alert, self.a_near, self.centre_a)
        self.assertEqual(mission.status, MissionStatus.JUST_DEFINED)


class QueueNameTests(SimpleTestCase):
    """
    Regression test for a bug that silently lost whole batches of readings.

    Subject and agent devices are numbered from separate sequences, and so are
    their record tables, so without the model type in the key subject device 1
    writing record 7 and agent device 1 writing record 7 shared one Redis list.
    Their readings interleaved, and the export then rejected the entire batch,
    because an agent record may only hold lat/lng/timestamp while a subject
    reading also carries a heart rate.
    """

    def test_same_device_and_record_number_do_not_collide(self):
        self.assertNotEqual(
            queue_name_for(ModelType.SUBJECT, 1, 7),
            queue_name_for(ModelType.AGENT, 1, 7),
        )

    def test_the_key_still_separates_devices_and_records(self):
        self.assertNotEqual(
            queue_name_for(ModelType.AGENT, 1, 7),
            queue_name_for(ModelType.AGENT, 2, 7),
        )
        self.assertNotEqual(
            queue_name_for(ModelType.AGENT, 1, 7),
            queue_name_for(ModelType.AGENT, 1, 8),
        )


# The routing stack without AllowedHostsOriginValidator, which has nothing to do
# with the consumers and would otherwise reject every test connection.
test_application = AuthMiddlewareStack(URLRouter(all_websocket_urlpatterns))


@override_settings(
    CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}},
)
class ConsumerTestCase(TransactionTestCase):
    """
    Base for the websocket tests.

    TransactionTestCase rather than TestCase because a consumer reaches the
    database from another thread through database_sync_to_async, and would not
    see rows held open in a test transaction.

    The export task is stubbed out: it is Celery's job, it is covered by the
    service tests, and letting it fire here would queue work against a database
    the worker cannot see. Redis itself is still real, so these tests need it
    running - which it is, wherever the rest of the stack is.
    """

    SUBJECT_AT = (44.4949, 11.3426)

    def setUp(self):
        patcher = patch('agents.consumers.export_from_redis_to_db.apply_async')
        self.export_task = patcher.start()
        self.addCleanup(patcher.stop)

        # Communicators opened by a test, closed by it through close_sockets().
        self.open_sockets = []

        self.now = timezone.now()
        self.region = Region.objects.create(
            name='Bologna', description='test region',
            polygon=Polygon.from_bbox((11.0, 44.2, 11.7, 44.8)),
        )

        self.centre_a = self._make_centre('panel-a@resc.com')
        self.centre_b = self._make_centre('panel-b@resc.com')

        # Centre A owns the nearer agent, so alerts here should route to A.
        self.a_near = self._make_agent(self.centre_a, 'a-near', 500)
        self.a_far = self._make_agent(self.centre_a, 'a-far', 4_000)
        self.b_mid = self._make_agent(self.centre_b, 'b-mid', 2_000)

        # Resolved here rather than in the tests: the tests are async, and a
        # related-manager lookup there would be a synchronous query.
        self.a_near_device = self.a_near.devices.first()
        self.a_far_device = self.a_far.devices.first()

        # A subject device takes its region from whoever it is registered to,
        # so it needs an owner with a profile in this region to connect at all.
        self.subject = User.objects.create_user(
            email='victim@resc.com', firstname='V', lastname='Ictim', password='x',
        )
        Profile.objects.filter(user=self.subject).update(
            type=ProfileType.NORMAL, region=self.region,
        )
        self.subject_device = SubjectDevice.objects.create(
            name='victim-device', subject=self.subject,
        )

    def _make_centre(self, email):
        user = User.objects.create_user(
            email=email, firstname='C', lastname='Entre', password='x',
        )
        Profile.objects.filter(user=user).update(
            type=ProfileType.EMERGENCY_CENTER, region=self.region,
        )
        return user

    def _make_agent(self, centre, name, metres_away):
        agent = Agent.objects.create(name=name, emergency_center=centre)
        AgentDevice.objects.create(
            agent=agent, name=f'{name}-device',
            last_location=north_of(ORIGIN, metres_away), last_seen=self.now,
        )
        return agent

    # ------------------------------------------------------------ helpers --

    db = staticmethod(sync_to_async)

    def token_for(self, user):
        now = datetime.datetime.now(datetime.timezone.utc)
        return jwt.encode(
            {'token_type': 'access', 'user_id': user.id, 'jti': 'test',
             'iat': now, 'exp': now + timedelta(minutes=10)},
            settings.SECRET_KEY, algorithm='HS256',
        )

    def panel_for(self, user):
        return WebsocketCommunicator(
            test_application, '/ws/center/panel/',
            headers=[(b'cookie', f'access_token={self.token_for(user)}'.encode())],
        )

    def device_for(self, path, device):
        return WebsocketCommunicator(
            test_application, path,
            headers=[(b'device', f'Resc {device.api_key}'.encode())],
        )

    async def connected(self, communicator):
        accepted, _ = await communicator.connect()
        self.assertTrue(accepted)
        self.open_sockets.append(communicator)
        return communicator

    async def await_message(self, communicator, key, timeout=4):
        """
        Read until a message carrying `key` arrives, or give up.

        Each read is given whatever is left of the budget rather than a short
        slice of it, because asgiref cancels the application when a read times
        out. Polling in small steps therefore kills the consumer on the first
        quiet moment, and every later read fails with CancelledError. Timing out
        here means nothing more was coming anyway.
        """
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                message = await communicator.receive_json_from(timeout=remaining)
            except asyncio.TimeoutError:
                return None
            if key in message:
                return message[key]

    async def send_subject_reading(self, lat=None, lng=None, heartrate=70):
        lat = self.SUBJECT_AT[0] if lat is None else lat
        lng = self.SUBJECT_AT[1] if lng is None else lng
        device = await self.connected(
            self.device_for('/ws/subject/send/', self.subject_device)
        )
        await device.send_json_to({
            'lat': lat, 'lng': lng, 'heartrate': heartrate,
            'timestamp': '2026-10-18 12:00:00',
        })
        # Give the consumer a moment to raise and route the alert.
        await asyncio.sleep(0.4)
        return device

    async def close_sockets(self):
        for communicator in self.open_sockets:
            try:
                await communicator.disconnect()
            except Exception:
                # A communicator whose read timed out has already had its
                # application cancelled by asgiref; disconnecting it again is
                # not interesting.
                pass
        self.open_sockets = []


class SubjectAlertRoutingTests(ConsumerTestCase):
    """A reading becomes a possible mission, for exactly one center."""

    async def test_alert_reaches_the_owner_of_the_nearest_agent_only(self):
        panel_a = await self.connected(self.panel_for(self.centre_a))
        panel_b = await self.connected(self.panel_for(self.centre_b))

        await self.send_subject_reading(heartrate=72)

        alert = await self.await_message(panel_a, 'alert')
        self.assertIsNotNone(alert, 'centre A owns the nearest agent and should be alerted')
        self.assertEqual(alert['subject_device_id'], self.subject_device.pk)
        self.assertEqual(alert['heartrate'], 72)

        self.assertIsNone(
            await self.await_message(panel_b, 'alert', timeout=1),
            'centre B owns no nearby agent and must not be told',
        )
        await self.close_sockets()

    async def test_repeat_readings_refresh_one_alert(self):
        await self.connected(self.panel_for(self.centre_a))

        device = await self.send_subject_reading(heartrate=70)
        for heartrate in (72, 74, 76):
            await device.send_json_to({
                'lat': self.SUBJECT_AT[0], 'lng': self.SUBJECT_AT[1],
                'heartrate': heartrate, 'timestamp': '2026-10-18 12:00:05',
            })
            await asyncio.sleep(0.3)

        self.assertEqual(await self.db(DistressAlert.objects.count)(), 1)
        await self.close_sockets()

    async def test_an_operator_connecting_late_is_sent_the_backlog(self):
        await self.send_subject_reading()

        panel_a = await self.connected(self.panel_for(self.centre_a))
        backlog = await self.await_message(panel_a, 'open_alerts')
        self.assertEqual(len(backlog), 1)

        panel_b = await self.connected(self.panel_for(self.centre_b))
        self.assertEqual(await self.await_message(panel_b, 'open_alerts'), [])
        await self.close_sockets()


class CenterPanelTests(ConsumerTestCase):

    async def test_roster_is_this_centers_own_agents(self):
        panel = await self.connected(self.panel_for(self.centre_a))
        roster = await self.await_message(panel, 'unoccupied_agents')

        self.assertEqual(
            sorted(agent['name'] for agent in roster),
            ['a-far', 'a-near'],
            "another center's agents must not be offered",
        )
        await self.close_sockets()

    async def test_ranked_agents_are_sorted_and_measured_in_metres(self):
        panel = await self.connected(self.panel_for(self.centre_a))
        await self.send_subject_reading()
        alert = await self.await_message(panel, 'alert')

        await panel.send_json_to({'type': 'rank_agents', 'alert_id': alert['id']})
        ranked = await self.await_message(panel, 'ranked_agents')

        self.assertEqual([agent['name'] for agent in ranked], ['a-near', 'a-far'])
        self.assertAlmostEqual(ranked[0]['distance_m'], 500, delta=15)
        await self.close_sockets()

    async def test_an_unknown_command_is_refused(self):
        panel = await self.connected(self.panel_for(self.centre_a))
        await panel.send_json_to({'type': 'nonsense'})

        error = await self.await_message(panel, 'error')
        self.assertEqual(error['code'], 'unknown_message')
        await self.close_sockets()

    async def test_a_running_mission_is_sent_to_a_panel_that_connects_later(self):
        """
        A mission outlives the page it was dispatched from. Without the backlog
        an operator who reloads sees nothing to finalise, the agent stays
        committed, and the subject - who already has a mission - raises no new
        alert either, so the centre is stuck with no way out.
        """
        first = await self.connected(self.panel_for(self.centre_a))
        await self.send_subject_reading()
        alert = await self.await_message(first, 'alert')
        await first.send_json_to({
            'type': 'dispatch', 'alert_id': alert['id'], 'agent_id': self.a_near.pk,
        })
        dispatched = await self.await_message(first, 'mission')
        await self.close_sockets()

        # A second operator, or the same one after a reload.
        later = await self.connected(self.panel_for(self.centre_a))
        backlog = await self.await_message(later, 'open_missions')

        self.assertEqual([m['id'] for m in backlog], [dispatched['id']])
        self.assertEqual(backlog[0]['agent_name'], self.a_near.name)
        await self.close_sockets()

    async def test_the_mission_backlog_is_this_centres_only(self):
        other = await self.connected(self.panel_for(self.centre_b))
        self.assertEqual(await self.await_message(other, 'open_missions'), [])
        await self.close_sockets()


class DispatchOverSocketsTests(ConsumerTestCase):
    """The whole cycle, driven the way a browser and a device would drive it."""

    async def test_a_center_cannot_dispatch_another_centers_agent(self):
        panel = await self.connected(self.panel_for(self.centre_a))
        await self.send_subject_reading()
        alert = await self.await_message(panel, 'alert')

        await panel.send_json_to({
            'type': 'dispatch', 'alert_id': alert['id'], 'agent_id': self.b_mid.pk,
        })

        error = await self.await_message(panel, 'error')
        self.assertEqual(error['code'], 'not_your_agent')
        self.assertEqual(await self.db(Mission.objects.count)(), 0)
        await self.close_sockets()

    async def test_dispatch_acknowledge_report_finalise(self):
        panel = await self.connected(self.panel_for(self.centre_a))
        agent_device = await self.connected(
            self.device_for('/ws/agent/send/', self.a_near_device)
        )

        await self.send_subject_reading()
        alert = await self.await_message(panel, 'alert')

        # --- dispatch -----------------------------------------------------
        await panel.send_json_to({
            'type': 'dispatch', 'alert_id': alert['id'], 'agent_id': self.a_near.pk,
        })

        assignment = await self.await_message(agent_device, 'mission_assigned')
        self.assertIsNotNone(assignment, 'the assignment must reach the device')
        mission_id = assignment['id']

        self.assertTrue(await self.db(lambda: Agent.objects.get(pk=self.a_near.pk).busy)())
        roster = await self.await_message(panel, 'unoccupied_agents')
        self.assertNotIn('a-near', [agent['name'] for agent in roster])

        # --- acknowledge --------------------------------------------------
        await agent_device.send_json_to({'type': 'mission_ack', 'mission_id': mission_id})
        await asyncio.sleep(0.4)
        self.assertEqual(
            await self.db(lambda: Mission.objects.get(pk=mission_id).status)(),
            MissionStatus.IN_PROGRESS,
        )

        # --- a reading is now recorded against the mission ----------------
        await agent_device.send_json_to({
            'lat': 44.4950, 'lng': 11.3427, 'timestamp': '2026-10-18 12:01:00',
        })
        await asyncio.sleep(0.4)
        self.assertEqual(
            await self.db(AgentRecords.objects.filter(mission_id=mission_id).count)(), 1,
        )

        # --- report -------------------------------------------------------
        await agent_device.send_json_to({
            'type': 'mission_report', 'mission_id': mission_id,
            'outcome': int(MissionOutcome.SUCCESS),
        })
        await asyncio.sleep(0.4)

        mission = await self.db(lambda: Mission.objects.get(pk=mission_id))()
        self.assertEqual(mission.status, MissionStatus.REPORTED)
        self.assertTrue(
            await self.db(lambda: Agent.objects.get(pk=self.a_near.pk).busy)(),
            'the agent stays committed until the center closes it',
        )

        # --- finalise -----------------------------------------------------
        await panel.send_json_to({'type': 'finalize', 'mission_id': mission_id})
        closed = await self.await_message(agent_device, 'mission_closed')

        self.assertIsNotNone(closed, 'the device must be told the mission ended')
        self.assertEqual(
            await self.db(lambda: Mission.objects.get(pk=mission_id).status)(),
            MissionStatus.CLOSED,
        )
        self.assertFalse(await self.db(lambda: Agent.objects.get(pk=self.a_near.pk).busy)())
        await self.close_sockets()

    async def test_abort_releases_the_agent_and_requeues_the_subject(self):
        panel = await self.connected(self.panel_for(self.centre_a))
        agent_device = await self.connected(
            self.device_for('/ws/agent/send/', self.a_near_device)
        )

        await self.send_subject_reading()
        alert = await self.await_message(panel, 'alert')
        await panel.send_json_to({
            'type': 'dispatch', 'alert_id': alert['id'], 'agent_id': self.a_near.pk,
        })
        assignment = await self.await_message(agent_device, 'mission_assigned')

        await panel.send_json_to({'type': 'abort', 'mission_id': assignment['id']})
        self.assertIsNotNone(await self.await_message(agent_device, 'mission_closed'))

        mission = await self.db(lambda: Mission.objects.get(pk=assignment['id']))()
        self.assertEqual(mission.status, MissionStatus.CLOSED)
        self.assertEqual(mission.outcome, MissionOutcome.ABORTED)
        self.assertFalse(await self.db(lambda: Agent.objects.get(pk=self.a_near.pk).busy)())
        self.assertEqual(
            await self.db(lambda: DistressAlert.objects.get(pk=alert['id']).status)(),
            AlertStatus.UNROUTED,
            'the subject is still trapped and must go back in the queue',
        )
        await self.close_sockets()


class AgentDeviceTests(ConsumerTestCase):

    async def test_an_agent_with_no_mission_is_visible_but_not_recorded(self):
        agent_device = await self.connected(
            self.device_for('/ws/agent/send/', self.a_near_device)
        )
        await agent_device.send_json_to({
            'lat': 44.4960, 'lng': 11.3430, 'timestamp': '2026-10-18 12:02:00',
        })
        await asyncio.sleep(0.4)

        device = await self.db(lambda: AgentDevice.objects.get(pk=self.a_near_device.pk))()
        self.assertAlmostEqual(device.last_location.y, 44.4960, places=4)
        self.assertAlmostEqual(device.last_location.x, 11.3430, places=4,
                               msg='longitude is x; swapping them is the classic bug here')
        self.assertEqual(await self.db(AgentRecords.objects.count)(), 0)
        await self.close_sockets()

    async def test_telemetry_without_a_type_field_still_works(self):
        """
        A device written before the mission messages existed sends a bare
        reading. Treating a missing type as telemetry is what keeps it working.
        """
        agent_device = await self.connected(
            self.device_for('/ws/agent/send/', self.a_near_device)
        )
        await agent_device.send_json_to({
            'lat': 44.4970, 'lng': 11.3440, 'timestamp': '2026-10-18 12:03:00',
        })
        await asyncio.sleep(0.4)

        device = await self.db(lambda: AgentDevice.objects.get(pk=self.a_near_device.pk))()
        self.assertAlmostEqual(device.last_location.y, 44.4970, places=4)
        await self.close_sockets()

    async def test_an_unknown_message_type_is_refused(self):
        agent_device = await self.connected(
            self.device_for('/ws/agent/send/', self.a_near_device)
        )
        await agent_device.send_json_to({'type': 'nonsense'})

        error = await self.await_message(agent_device, 'error')
        self.assertEqual(error['code'], 'unknown_message')
        await self.close_sockets()

    async def test_an_agent_cannot_acknowledge_another_agents_mission(self):
        panel = await self.connected(self.panel_for(self.centre_a))
        await self.send_subject_reading()
        alert = await self.await_message(panel, 'alert')
        await panel.send_json_to({
            'type': 'dispatch', 'alert_id': alert['id'], 'agent_id': self.a_near.pk,
        })
        mission = await self.await_message(panel, 'mission')

        intruder = await self.connected(
            self.device_for('/ws/agent/send/', self.a_far_device)
        )
        await intruder.send_json_to({'type': 'mission_ack', 'mission_id': mission['id']})

        error = await self.await_message(intruder, 'error')
        self.assertEqual(error['code'], 'not_your_mission')
        await self.close_sockets()


class SocketAuthTests(ConsumerTestCase):
    """The gates from roadmap items 1 and 2, pinned where they are enforced."""

    async def test_a_bad_token_is_rejected(self):
        communicator = WebsocketCommunicator(
            test_application, '/ws/center/panel/',
            headers=[(b'cookie', b'access_token=not.a.jwt')],
        )
        await communicator.connect()
        output = await communicator.receive_output(timeout=2)
        await communicator.disconnect()
        self.assertEqual(output.get('code'), 4001)

    async def test_a_normal_profile_is_rejected_with_its_own_code(self):
        """
        4005, not 4001: refreshing the token cannot fix the wrong kind of
        account, and the browser retries on 4001.
        """
        user = await self.db(User.objects.create_user)(
            email='normal@resc.com', firstname='N', lastname='Ormal', password='x',
        )
        await self.db(Profile.objects.filter(user=user).update)(
            type=ProfileType.NORMAL, region=self.region,
        )

        communicator = WebsocketCommunicator(
            test_application, '/ws/center/panel/',
            headers=[(b'cookie', f'access_token={self.token_for(user)}'.encode())],
        )
        await communicator.connect()
        output = await communicator.receive_output(timeout=2)
        await communicator.disconnect()
        self.assertEqual(output.get('code'), 4005)

    async def test_an_unknown_device_key_is_rejected(self):
        communicator = WebsocketCommunicator(
            test_application, '/ws/agent/send/',
            headers=[(b'device', b'Resc nonsense')],
        )
        await communicator.connect()
        output = await communicator.receive_output(timeout=2)
        await communicator.disconnect()
        self.assertEqual(output.get('code'), 4001)

    async def test_a_subject_device_with_no_owner_is_refused_not_crashed(self):
        """
        SubjectDevice.subject is nullable, and the region is read through it.
        Walking that chain blindly raised AttributeError, which the client saw
        as a 500 on the handshake rather than as a refusal it could act on.
        """
        orphan = await self.db(SubjectDevice.objects.create)(name='unregistered')

        communicator = WebsocketCommunicator(
            test_application, '/ws/subject/send/',
            headers=[(b'device', f'Resc {orphan.api_key}'.encode())],
        )
        await communicator.connect()
        output = await communicator.receive_output(timeout=2)
        await communicator.disconnect()
        self.assertEqual(output.get('code'), 4001)


class RootPanelTests(ConsumerTestCase):
    """
    The administrator's system-wide view: every region, every center's alerts,
    every mission - and no way to dispatch anything.
    """

    def setUp(self):
        super().setUp()
        self.root = User.objects.create_user(
            email='root@resc.com', firstname='R', lastname='Oot', password='x',
        )
        # Deliberately left with no region: a root account belongs to none, and
        # the fixture's own SUPER profile has none either.
        Profile.objects.filter(user=self.root).update(
            type=ProfileType.SUPER, region=None,
        )

    def root_panel(self):
        return WebsocketCommunicator(
            test_application, '/ws/root/panel/',
            headers=[(b'cookie', f'access_token={self.token_for(self.root)}'.encode())],
        )

    async def test_a_super_account_with_no_region_is_let_in(self):
        """
        Every other socket requires a region. Demanding one here would lock out
        the only kind of account this panel is for.
        """
        panel = await self.connected(self.root_panel())
        self.assertIsNotNone(await self.await_message(panel, 'snapshot'))
        await self.close_sockets()

    async def test_a_center_account_is_refused(self):
        communicator = WebsocketCommunicator(
            test_application, '/ws/root/panel/',
            headers=[(b'cookie', f'access_token={self.token_for(self.centre_a)}'.encode())],
        )
        await communicator.connect()
        output = await communicator.receive_output(timeout=2)
        await communicator.disconnect()
        self.assertEqual(output.get('code'), 4005)

    async def test_a_super_account_is_still_refused_the_center_panel(self):
        """
        The two panels have different gates. Opening one up must not open the
        other: a root account has no business dispatching.
        """
        communicator = WebsocketCommunicator(
            test_application, '/ws/center/panel/',
            headers=[(b'cookie', f'access_token={self.token_for(self.root)}'.encode())],
        )
        await communicator.connect()
        output = await communicator.receive_output(timeout=2)
        await communicator.disconnect()
        self.assertEqual(output.get('code'), 4005)

    async def test_the_snapshot_covers_the_whole_system(self):
        panel = await self.connected(self.root_panel())
        snapshot = await self.await_message(panel, 'snapshot')

        self.assertEqual(
            sorted(center['name'] for center in snapshot['centers']),
            sorted([str(self.centre_a), str(self.centre_b)]),
            'both centers, not just one region',
        )
        self.assertEqual(
            sorted(agent['name'] for agent in snapshot['agents']),
            ['a-far', 'a-near', 'b-mid'],
            "every center's agents, which no center panel ever sees",
        )
        self.assertIn('victim-device', [d['name'] for d in snapshot['subject_devices']])

        near = next(a for a in snapshot['agents'] if a['name'] == 'a-near')
        self.assertFalse(near['busy'])
        self.assertAlmostEqual(near['lat'], north_of(ORIGIN, 500).y, places=4)
        await self.close_sockets()

    async def test_it_sees_alerts_routed_to_any_center(self):
        panel = await self.connected(self.root_panel())
        await self.await_message(panel, 'snapshot')

        await self.send_subject_reading(heartrate=77)

        alert = await self.await_message(panel, 'alert')
        self.assertIsNotNone(alert, 'the root watches every center, not one')
        self.assertEqual(alert['heartrate'], 77)
        await self.close_sockets()

    async def test_it_sees_an_alert_that_no_center_could_be_given(self):
        """
        An alert with no free agent anywhere has nobody to notify, which is
        precisely the situation an administrator needs to notice.
        """
        await self.db(Agent.objects.update)(busy=True)

        panel = await self.connected(self.root_panel())
        await self.await_message(panel, 'snapshot')
        await self.send_subject_reading()

        alert = await self.await_message(panel, 'alert')
        self.assertIsNotNone(alert, 'an unrouted alert must still reach the root')
        self.assertEqual(alert['status'], AlertStatus.UNROUTED)
        await self.close_sockets()

    async def test_it_follows_a_mission_through_its_whole_life(self):
        panel = await self.connected(self.root_panel())
        center = await self.connected(self.panel_for(self.centre_a))
        agent_device = await self.connected(
            self.device_for('/ws/agent/send/', self.a_near_device)
        )
        await self.await_message(panel, 'snapshot')

        await self.send_subject_reading()
        alert = await self.await_message(center, 'alert')

        await center.send_json_to({
            'type': 'dispatch', 'alert_id': alert['id'], 'agent_id': self.a_near.pk,
        })
        mission = await self.await_message(panel, 'mission')
        self.assertIsNotNone(mission, 'the root should see the dispatch')
        self.assertEqual(mission['status'], MissionStatus.JUST_DEFINED)

        await agent_device.send_json_to({
            'type': 'mission_ack', 'mission_id': mission['id'],
        })
        self.assertEqual(
            (await self.await_message(panel, 'mission'))['status'],
            MissionStatus.IN_PROGRESS,
            'and the acknowledgement, which came from the device not the center',
        )
        await self.close_sockets()

    async def test_it_sees_devices_moving_in_every_region(self):
        panel = await self.connected(self.root_panel())
        await self.await_message(panel, 'snapshot')

        agent_device = await self.connected(
            self.device_for('/ws/agent/send/', self.a_near_device)
        )
        await agent_device.send_json_to({
            'lat': 44.4980, 'lng': 11.3450, 'timestamp': '2026-10-19 10:00:00',
        })

        reading = await self.await_message(panel, 'device_data')
        self.assertIsNotNone(reading)
        self.assertAlmostEqual(reading['lat'], 44.4980, places=4)
        await self.close_sockets()

    async def test_it_cannot_dispatch(self):
        """Read only: deciding a mission belongs to the center that owns the agent."""
        panel = await self.connected(self.root_panel())
        await self.await_message(panel, 'snapshot')

        await panel.send_json_to({'type': 'dispatch', 'alert_id': 1, 'agent_id': 1})

        # The consumer has no receive(), so the message is simply ignored - what
        # matters is that nothing was created.
        await asyncio.sleep(0.4)
        self.assertEqual(await self.db(Mission.objects.count)(), 0)
        await self.close_sockets()
