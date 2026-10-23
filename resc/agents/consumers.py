from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.gis.geos import Point
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from resc.redis_conf import RSCREDIS
from agents import services
from agents.models import (
    SubjectRecords, AgentRecords, Agent, Mission, DistressAlert, Region, SubjectDevice,
)
from agents.tasks import export_from_redis_to_db
from agents.mixinx import AliveSubjectAuthMixin, AgentAuthMixin, JWTConsumerAuthMixin
from agents.utils import ModelType, MissionStatus, AlertStatus
from profiles.models import Profile
from profiles.utils import ProfileType

import json


def center_group_name(emergency_center_pk) :
    """
    Alerts, mission updates and the dispatch roster all concern one center
    rather than everybody in the region, so they need a group keyed by center.
    The region group remains what the *map* is built on.
    """
    return f'center-{emergency_center_pk}'


def queue_name_for(model_type, device_pk, record_pk) :
    """
    The Redis list a device's readings are buffered in.

    The model type has to be part of the key. Subject and agent devices are
    numbered from separate sequences, and so are their record tables, so subject
    device 1 writing record 7 and agent device 1 writing record 7 would
    otherwise share one list. Their readings would interleave, and the export
    would then reject the whole batch, because an agent record may only contain
    lat/lng/timestamp and a subject reading also carries a heart rate.
    """
    return f'queue:{model_type}:{device_pk}:{record_pk}'


def agent_group_name(agent_pk) :
    """
    Keyed by agent rather than by device: an assignment is given to a person,
    and if they happen to carry two devices both should hear about it.
    """
    return f'agent-{agent_pk}'


# The root panel watches the whole system rather than one region or one center,
# so alerts and missions are published here as well as to whoever owns them.
ROOT_GROUP_NAME = 'root-panel'


async def publish_alert(channel_layer, center_pk, payload) :
    """Send a possible mission to the center it was routed to, and to the root."""
    if center_pk is not None :
        await channel_layer.group_send(
            center_group_name(center_pk),
            {'type': 'alert_update', 'value': payload},
        )
    await channel_layer.group_send(
        ROOT_GROUP_NAME,
        {'type': 'alert_update', 'value': payload},
    )


async def publish_mission(channel_layer, center_pk, payload) :
    """Send a mission update to the center that owns it, and to the root."""
    if center_pk is not None :
        await channel_layer.group_send(
            center_group_name(center_pk),
            {'type': 'mission_update', 'value': payload},
        )
    await channel_layer.group_send(
        ROOT_GROUP_NAME,
        {'type': 'mission_update', 'value': payload},
    )


def alert_payload(alert, *, heartrate=None) :
    """
    One shape for a possible mission, used both for the backlog sent on connect
    and for live updates, so the two cannot drift apart.

    Heart rate belongs to the reading rather than to the alert, so it is only
    present on a live push.
    """
    return {
        'id': alert.pk,
        'status': alert.status,
        'subject_device_id': alert.subject_device_id,
        'subject_device_name': alert.subject_device.name,
        'lat': alert.location.y,
        'lng': alert.location.x,
        'heartrate': heartrate,
        'first_seen': alert.first_seen.isoformat(),
        'last_seen': alert.last_seen.isoformat(),
    }


def mission_payload(mission) :
    """
    One shape for a mission, shared by the center panel and the agent's device.

    Must be built in a sync context: it reads mission.agent.name, which is a
    lazy foreign key and would raise SynchronousOnlyOperation from a consumer.
    """
    return {
        'id': mission.pk,
        'status': mission.status,
        'outcome': mission.outcome,
        'agent_id': mission.agent_id,
        'agent_name': mission.agent.name,
        'subject_device_id': mission.subject_device_id,
        'lat': mission.location.y,
        'lng': mission.location.x,
        'acknowledged_at': mission.acknowledged_at.isoformat() if mission.acknowledged_at else None,
        'reported_at': mission.reported_at.isoformat() if mission.reported_at else None,
        'closed_at': mission.closed_at.isoformat() if mission.closed_at else None,
    }


@database_sync_to_async
def update_device_position(device, lat, lng) :
    """
    Overwrite the device's current position.

    The readings themselves go to the record tables in batches of a hundred, so
    they cannot answer "where is this device now". This is a single indexed
    UPDATE per reading, which is what the nearest-agent query reads.

    The timestamp is taken from the server rather than from the device's own
    reading: device clocks drift, and the value in the payload is a naive string.
    Note the Point argument order is (x, y), so longitude first.
    """
    return type(device).objects.filter(pk=device.pk).update(
        last_location=Point(float(lng), float(lat), srid=4326),
        last_seen=timezone.now(),
    )


class AgentConsumer(AgentAuthMixin, AsyncWebsocketConsumer):

    """
    An agent device transmits continuously so that the agent stays visible on the
    map, but only what it sends while on a mission is recorded. So every reading
    updates the current position and goes out to the region feed, while buffering
    to Redis happens only between start_recording and stop_recording.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.model = AgentRecords
        self.model_type = ModelType.AGENT
        self.redis = RSCREDIS.db
        self.queue_size = 100
        # No record until a mission is under way. While these are None the
        # consumer broadcasts but writes nothing.
        self.mission = None
        self.record = None
        self.queue_name = None
        self.counter = 0

    async def connect(self):
        if not await super().connect():
            return

        self.device = self.scope["device"]
        self.region = self.scope["region"]

        self.publish_group_name = f'publish-agent-{self.device.pk}'
        self.region_group_name = f'region-{self.region.pk}'
        self.agent_group_name = agent_group_name(self.device.agent_id)

        await self.channel_layer.group_add(
            self.publish_group_name,
            self.channel_name
        )
        # The downlink. Until this existed the socket was one-way and an
        # assignment had no way of reaching the agent at all.
        await self.channel_layer.group_add(
            self.agent_group_name,
            self.channel_name
        )

        await self.accept()

        # An agent can drop its connection in the middle of a mission and come
        # back, so pick the mission up again rather than losing the rest of it.
        mission = await self.get_active_mission()
        if mission is not None :
            await self.start_recording(mission)

    async def receive(self, text_data=None):
        """
        Telemetry, or one of the mission messages.

        A reading carries no 'type' key, which is how the two are told apart and
        why devices written before the mission messages existed keep working
        unchanged.
        """
        if not text_data :
            return

        data = json.loads(text_data)
        message_type = data.get('type')

        if message_type is None :
            await self.handle_telemetry(data)
        elif message_type == 'mission_ack' :
            await self.handle_ack(data)
        elif message_type == 'mission_report' :
            await self.handle_report(data)
        else :
            await self.send_error('unknown_message', _('Unknown message type'))

    async def handle_telemetry(self, data) :
        device_data = {
            'lat': data["lat"],
            'lng': data["lng"],
            'timestamp': data["timestamp"],
        }

        await update_device_position(self.device, data["lat"], data["lng"])

        # Recorded only while on a mission.
        if self.record is not None :
            await self.channel_layer.group_send(
                self.publish_group_name,
                {
                    'type': 'processing',
                    'value': {**device_data}
                }
            )

        device_data['region'] = f'region-{self.region.pk}'
        device_data['type'] = self.model_type
        device_data['pk'] = self.device.pk
        await self.channel_layer.group_send(
            self.region_group_name,
            {
                'type': 'echo',
                'value': {**device_data}
            }
        )

    async def send_error(self, code, message) :
        await self.send(text_data=json.dumps({
            'error': {'code': code, 'message': str(message)}
        }))

    @database_sync_to_async
    def _acknowledge(self, mission_id) :
        mission = Mission.objects.select_related('agent').get(pk=mission_id)
        mission = services.acknowledge_mission(mission, self.device.agent)
        return mission, mission_payload(mission), mission.emergency_center_id

    @database_sync_to_async
    def _report(self, mission_id, outcome) :
        mission = Mission.objects.select_related('agent').get(pk=mission_id)
        mission = services.report_mission(mission, self.device.agent, outcome)
        return mission_payload(mission), mission.emergency_center_id

    async def handle_ack(self, data) :
        """
        The agent confirms the assignment, which is what starts the mission -
        and what starts recording their track.
        """
        try :
            mission, payload, center_pk = await self._acknowledge(data['mission_id'])
        except KeyError :
            return await self.send_error('bad_request', _('mission_id is required'))
        except Mission.DoesNotExist :
            return await self.send_error('not_found', _('No such mission'))
        except services.DispatchError as error :
            return await self.send_error(error.code, error)

        await self.start_recording(mission)
        await self.send(text_data=json.dumps({'mission': payload}))
        await self.notify_center(center_pk, payload)

    async def handle_report(self, data) :
        """
        The agent reports how it went. The mission is not closed by this - the
        center still has to finalise it - but the field work is over, so the
        recording stops here.
        """
        try :
            payload, center_pk = await self._report(data['mission_id'], data['outcome'])
        except KeyError :
            return await self.send_error('bad_request', _('mission_id and outcome are required'))
        except Mission.DoesNotExist :
            return await self.send_error('not_found', _('No such mission'))
        except services.DispatchError as error :
            return await self.send_error(error.code, error)

        await self.stop_recording()
        await self.send(text_data=json.dumps({'mission': payload}))
        await self.notify_center(center_pk, payload)

    async def notify_center(self, center_pk, payload) :
        await publish_mission(self.channel_layer, center_pk, payload)

    async def mission_assigned(self, event) :
        """Group handler: the center has dispatched this agent."""
        await self.send(text_data=json.dumps({
            'mission_assigned': event['value']
        }))

    async def mission_closed(self, event) :
        """
        Group handler: the mission is over, whether finalised or called off.

        Stop recording either way - on an abort the agent may well still be in
        the field, but what they do next is not part of a mission that no longer
        exists.
        """
        await self.stop_recording()
        await self.send(text_data=json.dumps({
            'mission_closed': event['value']
        }))

    async def processing(self, event) :
        data = event['value']
        await self.add_to_db(data)

    async def disconnect(self, close_code=None):
        # Whatever is still buffered belongs to the mission; don't drop its tail.
        await self.stop_recording()

        # connect() may have bailed out before the groups were joined
        for attribute in ('publish_group_name', 'agent_group_name') :
            group = getattr(self, attribute, None)
            if group:
                await self.channel_layer.group_discard(group, self.channel_name)

    @database_sync_to_async
    def get_active_mission(self) :
        """
        The mission this device's agent is currently out on, if any.

        Only IN_PROGRESS counts: the agent has acknowledged and is working. Once
        they report an outcome the field work is over, and the journey back is
        not part of the mission record.
        """
        return Mission.objects.filter(
                        agent=self.device.agent,
                        status=MissionStatus.IN_PROGRESS,
                        ).first()

    async def start_recording(self, mission) :
        """Begin recording this device's readings against a mission."""
        if self.record is not None :
            return

        self.mission = mission
        self.record = await self.create_record(mission)
        self.queue_name = queue_name_for(self.model_type, self.device.pk, self.record.pk)
        self.counter = 0

    async def stop_recording(self) :
        """Flush whatever is buffered and stop recording."""
        if self.record is None :
            return

        await self.flush_queue()
        self.mission = None
        self.record = None
        self.queue_name = None

    @database_sync_to_async
    def create_record(self, mission) :
        kw = {
            'device':self.device,
            'mission':mission,
            'data':[]
        }
        return self.model.objects.create(**kw)

    async def add_to_db(self, value) :
        if self.record is None :
            return

        value_str = json.dumps(value)
        self.redis.rpush(self.queue_name, value_str)
        # '>=' rather than '==': if the queue ever overshoots, an equality test
        # would never match again and the device would stop flushing for good.
        if self.redis.llen(self.queue_name) >= self.queue_size :
            await self.flush_queue()

    async def flush_queue(self) :
        """
        Hand whatever is buffered to the export task.

        Renaming the key hands the batch over atomically, so readings arriving
        during the export land on a fresh queue rather than being exported twice.
        """
        if self.queue_name is None :
            return

        pending = self.redis.llen(self.queue_name)
        if not pending :
            return

        prime_queue = f'{self.queue_name}-prime:{self.counter}'
        self.redis.rename(self.queue_name, prime_queue)
        export_from_redis_to_db.apply_async(kwargs={
                            'model': self.model_type,
                            'record_id': str(self.record.pk),
                            'queue_name': prime_queue,
                            'queue_size': pending,
                            })
        self.counter = self.counter + 1


class CenterPanelConsumer(JWTConsumerAuthMixin, AsyncWebsocketConsumer):
    """
    An emergency center's own panel.

    Two feeds share this socket because they are two halves of one decision: who
    needs help, and who is free to go. It carries the roster of available agents,
    which is region-wide, and the possible missions routed to *this* center,
    which are not - hence the per-center group alongside the regional one.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def connect(self):
        if not await super().connect():
            return

        self.region = self.scope["region"]
        self.center = self.scope["account"]

        # One group, because everything this socket carries - the roster, the
        # alerts, the mission updates - concerns this center alone. An agent
        # going busy changes nobody else's roster.
        self.center_group_name = center_group_name(self.center.pk)

        await self.channel_layer.group_add(
            self.center_group_name,
            self.channel_name
        )

        await self.accept()
        await self.send_unoccupied_agents()
        # Work raised or started while nobody was connected is still waiting,
        # so an operator starts from the backlog rather than from whatever
        # happens to arrive next. Missions matter as much as alerts here: a
        # mission outlives the page it was dispatched from, and one that cannot
        # be seen cannot be finalised.
        await self.send_open_alerts()
        await self.send_open_missions()

    async def disconnect(self, close_code=None):
        # connect() may have bailed out before the group was joined
        group = getattr(self, 'center_group_name', None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def agents_update(self, event) :
        """
        Group handler: re-send the roster when an agent's availability changes.

        Nothing publishes to this group yet - the dispatch workflow will, as it
        flips Agent.busy. Without a handler, joining the group is pointless and
        any group_send to it would raise.
        """
        await self.send(text_data=json.dumps({
            'unoccupied_agents': event['value']
        }))

    async def alert_update(self, event) :
        """Group handler: a possible mission was raised, or has moved."""
        await self.send(text_data=json.dumps({
            'alert': event['value']
        }))

    @database_sync_to_async
    def get_open_alerts(self) :
        return [alert_payload(alert)
                for alert in services.open_alerts_for_center(self.center)]

    async def send_open_alerts(self) :
        await self.send(text_data=json.dumps({
            'open_alerts': await self.get_open_alerts()
        }))

    @database_sync_to_async
    def get_open_missions(self) :
        return [mission_payload(mission)
                for mission in services.open_missions_for_center(self.center)]

    async def send_open_missions(self) :
        await self.send(text_data=json.dumps({
            'open_missions': await self.get_open_missions()
        }))

    @database_sync_to_async
    def get_unoccupied_agents(self) :
        """
        This center's own free agents.

        Scoped to the center rather than the region: a center may never dispatch
        another center's agent, so listing them would only invite a request that
        create_mission is going to refuse.

        The queryset has to be evaluated here, inside the sync context. Iterating
        it from the async consumer raises SynchronousOnlyOperation.
        """
        agents = Agent.objects.filter(emergency_center=self.center, busy=False)
        # The id is what a dispatch request names the agent by.
        return [{'id': agent.pk, 'name': agent.name} for agent in agents]

    async def send_unoccupied_agents(self):
        await self.send(text_data=json.dumps({
            'unoccupied_agents': await self.get_unoccupied_agents()
        }))

    async def send_error(self, code, message) :
        await self.send(text_data=json.dumps({
            'error': {'code': code, 'message': str(message)}
        }))

    async def mission_update(self, event) :
        """Group handler: a mission this center owns has moved."""
        await self.send(text_data=json.dumps({
            'mission': event['value']
        }))

    # ------------------------------------------------------------ commands --

    async def receive(self, text_data=None) :
        """
        The operator's decisions. Dispatching is deliberately a human act, so
        this socket is the only way a mission ever gets created.
        """
        if not text_data :
            return

        try :
            message = json.loads(text_data)
        except ValueError :
            return await self.send_error('bad_request', _('Malformed message'))

        handlers = {
            'rank_agents': self.handle_rank_agents,
            'dispatch': self.handle_dispatch,
            'dismiss': self.handle_dismiss,
            'abort': self.handle_abort,
            'finalize': self.handle_finalize,
        }
        handler = handlers.get(message.get('type'))
        if handler is None :
            return await self.send_error('unknown_message', _('Unknown message type'))

        try :
            await handler(message)
        except KeyError as missing :
            await self.send_error('bad_request', _('Missing field: %s') % missing)
        except (DistressAlert.DoesNotExist, Mission.DoesNotExist, Agent.DoesNotExist) :
            await self.send_error('not_found', _('No such object'))
        except services.DispatchError as error :
            await self.send_error(error.code, error)

    @database_sync_to_async
    def _rank_agents(self, alert_id) :
        alert = DistressAlert.objects.get(pk=alert_id, emergency_center=self.center)
        ranked = services.rank_agents_for_center(self.center, alert.location)
        return [{'id': agent.pk,
                 'name': agent.name,
                 # distance comes back as a measure object, not a number.
                 'distance_m': round(agent.distance.m)}
                for agent in ranked]

    async def handle_rank_agents(self, message) :
        """
        The ranked list only makes sense against a place, so it is asked for per
        alert rather than pushed. The roster sent on connect is the unranked
        version, for when nothing is selected.
        """
        alert_id = message['alert_id']
        await self.send(text_data=json.dumps({
            'alert_id': alert_id,
            'ranked_agents': await self._rank_agents(alert_id),
        }))

    @database_sync_to_async
    def _dispatch(self, alert_id, agent_id) :
        alert = DistressAlert.objects.get(pk=alert_id)
        agent = Agent.objects.get(pk=agent_id)
        mission = services.create_mission(alert, agent, self.center)
        return mission_payload(mission), mission.agent_id

    async def handle_dispatch(self, message) :
        payload, agent_pk = await self._dispatch(message['alert_id'], message['agent_id'])

        await self.channel_layer.group_send(
            agent_group_name(agent_pk),
            {'type': 'mission_assigned', 'value': payload},
        )
        await self.broadcast_mission(payload)
        await self.broadcast_roster()

    @database_sync_to_async
    def _dismiss(self, alert_id) :
        alert = DistressAlert.objects.select_related('subject_device').get(pk=alert_id)
        return alert_payload(services.dismiss_alert(alert, self.center))

    async def handle_dismiss(self, message) :
        payload = await self._dismiss(message['alert_id'])
        await publish_alert(self.channel_layer, self.center.pk, payload)

    @database_sync_to_async
    def _abort(self, mission_id) :
        mission = Mission.objects.select_related('agent').get(pk=mission_id)
        mission = services.abort_mission(mission, self.center)
        return mission_payload(mission), mission.agent_id

    async def handle_abort(self, message) :
        payload, agent_pk = await self._abort(message['mission_id'])
        await self.announce_closed(payload, agent_pk)

    @database_sync_to_async
    def _finalize(self, mission_id, outcome) :
        mission = Mission.objects.select_related('agent').get(pk=mission_id)
        mission = services.finalize_mission(mission, self.center, outcome=outcome)
        return mission_payload(mission), mission.agent_id

    async def handle_finalize(self, message) :
        payload, agent_pk = await self._finalize(message['mission_id'], message.get('outcome'))
        await self.announce_closed(payload, agent_pk)

    async def announce_closed(self, payload, agent_pk) :
        """A closed mission frees its agent, so the roster changes too."""
        await self.channel_layer.group_send(
            agent_group_name(agent_pk),
            {'type': 'mission_closed', 'value': payload},
        )
        await self.broadcast_mission(payload)
        await self.broadcast_roster()

    async def broadcast_mission(self, payload) :
        await publish_mission(self.channel_layer, self.center.pk, payload)

    async def broadcast_roster(self) :
        """
        Sent to the group rather than to this socket, so that a center with two
        operators logged in does not leave one of them looking at a stale list.
        """
        await self.channel_layer.group_send(
            self.center_group_name,
            {'type': 'agents_update', 'value': await self.get_unoccupied_agents()},
        )


class RootPanelConsumer(JWTConsumerAuthMixin, AsyncWebsocketConsumer):
    """
    A system-wide view, for an administrator rather than a single center.

    Read only: it watches every region, every center's alerts and every
    mission, but it dispatches nothing. Deciding a mission belongs to the
    center that owns the agent, and giving an administrator a way around that
    would quietly undo the rule.

    This is the one socket that is not scoped to a region - it joins every
    region's feed instead - which is why it does not require the account to
    have one. The SUPER profile in the fixture has no region at all.
    """

    allowed_profile_types = (ProfileType.SUPER, )
    requires_region = False

    # How much closed history to send on connect. Open work is always included;
    # this only bounds the tail.
    closed_missions_shown = 20

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.region_groups = []

    async def connect(self):
        if not await super().connect():
            return

        self.account = self.scope["account"]

        await self.channel_layer.group_add(ROOT_GROUP_NAME, self.channel_name)

        # Every region's device feed, so the map covers the whole system rather
        # than one city. Regions created after this socket opened are not
        # picked up until it reconnects.
        self.region_groups = await self.get_region_groups()
        for group in self.region_groups :
            await self.channel_layer.group_add(group, self.channel_name)

        await self.accept()
        await self.send_snapshot()

    async def disconnect(self, close_code=None):
        # connect() may have bailed out before any group was joined
        if getattr(self, 'region_groups', None) is not None :
            await self.channel_layer.group_discard(ROOT_GROUP_NAME, self.channel_name)
            for group in self.region_groups :
                await self.channel_layer.group_discard(group, self.channel_name)

    @database_sync_to_async
    def get_region_groups(self) :
        return [f'region-{pk}' for pk in Region.objects.values_list('pk', flat=True)]

    # ------------------------------------------------------------- feeds --

    async def echo(self, event) :
        """A device moved, in any region."""
        await self.send(text_data=json.dumps({'device_data': event['value']}))

    async def alert_update(self, event) :
        await self.send(text_data=json.dumps({'alert': event['value']}))

    async def mission_update(self, event) :
        await self.send(text_data=json.dumps({'mission': event['value']}))

    # ---------------------------------------------------------- snapshot --

    @database_sync_to_async
    def get_snapshot(self) :
        """
        Everything worth seeing on arrival, so the panel starts populated
        rather than waiting for something to happen.
        """
        centers = (Profile.objects
                   .filter(type=ProfileType.EMERGENCY_CENTER)
                   .select_related('user', 'region', 'location'))

        agents = (Agent.objects
                  .select_related('emergency_center')
                  .prefetch_related('devices')
                  .order_by('emergency_center_id', 'name'))

        open_missions = (Mission.objects
                         .filter(status__in=MissionStatus.open_statuses())
                         .select_related('agent', 'emergency_center'))
        closed_missions = (Mission.objects
                           .exclude(status__in=MissionStatus.open_statuses())
                           .select_related('agent', 'emergency_center')
                           .order_by('-closed_at')[:self.closed_missions_shown])

        alerts = (DistressAlert.objects
                  .filter(status__in=AlertStatus.open_statuses())
                  .select_related('subject_device', 'emergency_center')
                  .order_by('-last_seen'))

        def located(device) :
            if device is None or device.last_location is None :
                return {'lat': None, 'lng': None, 'last_seen': None}
            return {
                'lat': device.last_location.y,
                'lng': device.last_location.x,
                'last_seen': device.last_seen.isoformat() if device.last_seen else None,
            }

        def agent_row(agent) :
            # The agent's own position is whichever device last reported one.
            reporting = [d for d in agent.devices.all() if d.last_location is not None]
            latest = max(reporting, key=lambda d: d.last_seen, default=None) if reporting else None
            return {
                'id': agent.pk,
                'name': agent.name,
                'busy': agent.busy,
                'center_id': agent.emergency_center_id,
                'center': str(agent.emergency_center),
                **located(latest),
            }

        def mission_row(mission) :
            return {**mission_payload(mission),
                    'center': str(mission.emergency_center)}

        return {
            'centers': [{
                'id': profile.user_id,
                'name': str(profile.user),
                'region': str(profile.region) if profile.region else None,
                'lat': profile.location.location.y if profile.location else None,
                'lng': profile.location.location.x if profile.location else None,
            } for profile in centers],
            'agents': [agent_row(agent) for agent in agents],
            'subject_devices': [{
                'id': device.pk,
                'name': device.name,
                'subject': str(device.subject) if device.subject else None,
                **located(device),
            } for device in SubjectDevice.objects.select_related('subject')],
            'alerts': [{**alert_payload(alert),
                        'center': str(alert.emergency_center) if alert.emergency_center else None}
                       for alert in alerts],
            'open_missions': [mission_row(mission) for mission in open_missions],
            'closed_missions': [mission_row(mission) for mission in closed_missions],
        }

    async def send_snapshot(self) :
        await self.send(text_data=json.dumps({'snapshot': await self.get_snapshot()}))


class EmergencyReceiveConsumer(JWTConsumerAuthMixin, AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def connect(self):
        if not await super().connect():
            return

        self.region = self.scope["region"]
        self.region_group_name = f'region-{self.region.pk}'
        await self.channel_layer.group_add(
            self.region_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code=None):
        # connect() may have bailed out before the group was joined
        group = getattr(self, 'region_group_name', None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def echo(self, event) :
        device_data = event['value']
        # print(device_data)
        await self.send(text_data=json.dumps({'device_data': device_data}))


class AliveSubjectConsumer(AliveSubjectAuthMixin, AsyncWebsocketConsumer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.model = SubjectRecords
        self.model_type = ModelType.SUBJECT
        self.redis = RSCREDIS.db
        self.queue_size = 100

    async def connect(self):
        if not await super().connect():
            return

        self.device = self.scope["device"]
        self.region = self.scope["region"]

        # CREATE A RECORD
        self.record = await database_sync_to_async(self.create_record)()

        # GET REDIS DATABASE
        self.queue_name = queue_name_for(self.model_type, self.device.pk, self.record.pk)
        self.counter = 0

        self.publish_group_name = f'publish-subject-{self.device.pk}'
        self.region_group_name = f'region-{self.region.pk}'

        await self.channel_layer.group_add(
            self.publish_group_name,
            self.channel_name
        )

        await self.accept()

    async def receive(self, text_data=None):
        """
        The data includes the region which belongs to the corresponding user's profile
        ** for future updates, it is better to get lattitude and longitude, check which region they belong to
        ** and send data to the related 'region_group_name' according to the region
        """
        if text_data :
            data = json.loads(text_data)
            device_data = {
                'lat': data["lat"],
                'lng': data["lng"],
                'heartrate': data["heartrate"],
                'timestamp': data["timestamp"],
            }

            await update_device_position(self.device, data["lat"], data["lng"])

            # A subject device only transmits during a disaster, so the reading
            # itself is the distress signal and this is what raises the alert.
            await self.raise_alert(data["lat"], data["lng"], data.get("heartrate"))

            # For the same reason, everything it sends is worth recording.
            await self.channel_layer.group_send(
                self.publish_group_name,
                {
                    'type': 'processing',
                    'value': {**device_data}
                }
            )

            device_data['region'] = f'region-{self.region.pk}'
            device_data['type'] = self.model_type
            device_data['pk'] = self.device.pk
            await self.channel_layer.group_send(
                self.region_group_name,
                {
                    'type': 'echo',
                    'value': {**device_data}
                }
            )

    @database_sync_to_async
    def _handle_reading(self, lat, lng) :
        """
        Hand the reading to the dispatch rules, and shape whatever comes back.

        The payload is built here, inside the sync context, because reading
        alert.subject_device.name lazily from the async consumer would raise
        SynchronousOnlyOperation.
        """
        point = Point(float(lng), float(lat), srid=4326)
        alert, created, center = services.handle_subject_reading(
                                        self.device, point, self.region,
                                        )
        if alert is None :
            # The subject already has a mission under way, so this reading is
            # part of a rescue in progress and raises nothing.
            return None, None

        # center is None when no agent was free anywhere in the region. The
        # alert still goes out, with nobody to address it to: the root panel
        # watches for exactly that, and a later reading will route it.
        return (center.pk if center is not None else None), alert_payload(alert)

    async def raise_alert(self, lat, lng, heartrate) :
        center_pk, payload = await self._handle_reading(lat, lng)
        if payload is None :
            return

        payload['heartrate'] = heartrate
        await publish_alert(self.channel_layer, center_pk, payload)

    async def processing(self, event) :
        data = event['value']
        await self.add_to_db(data)

    async def disconnect(self, close_code=None):
        # A subject device disconnecting is the normal end of an episode, and
        # whatever is still buffered is distress data. Don't drop it.
        await self.flush_queue()

        # connect() may have bailed out before the group was joined
        group = getattr(self, 'publish_group_name', None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    def create_record(self) :
        kw = {
            'device':self.device,
            'data':[]
        }
        return self.model.objects.create(**kw)

    async def add_to_db(self, value) :
        value_str = json.dumps(value)
        self.redis.rpush(self.queue_name, value_str)
        # '>=' rather than '==': if the queue ever overshoots, an equality test
        # would never match again and the device would stop flushing for good.
        if self.redis.llen(self.queue_name) >= self.queue_size :
            await self.flush_queue()

    async def flush_queue(self) :
        """Hand whatever is buffered to the export task. See AgentConsumer."""
        if getattr(self, 'queue_name', None) is None :
            return

        pending = self.redis.llen(self.queue_name)
        if not pending :
            return

        prime_queue = f'{self.queue_name}-prime:{self.counter}'
        self.redis.rename(self.queue_name, prime_queue)
        export_from_redis_to_db.apply_async(kwargs={
                            'model': self.model_type,
                            'record_id': str(self.record.pk),
                            'queue_name': prime_queue,
                            'queue_size': pending,
                            })
        self.counter = self.counter + 1
