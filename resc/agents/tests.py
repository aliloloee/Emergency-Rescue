"""
Tests for the dispatch rules in agents.services.

These run against a real PostGIS test database but never touch a channel layer,
so they are fast and they exercise the rules rather than the plumbing.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point, Polygon
from django.test import TestCase
from django.utils import timezone

from agents import services
from agents.models import Agent, AgentDevice, DistressAlert, Mission, Region, SubjectDevice
from agents.utils import AlertStatus, MissionOutcome, MissionStatus
from profiles.models import Profile
from profiles.utils import ProfileType

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
