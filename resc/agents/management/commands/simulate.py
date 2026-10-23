"""
Drive a whole rescue from the command line, so the dashboard can be watched
while it happens.

The notebooks in communication-scripts/ do the same thing, but they need a
Python and a Jupyter on the machine you are sitting at. This runs inside the
container, against the same websockets, so there is nothing to install:

    docker-compose exec web python /app/resc/manage.py simulate

It plays the part of both devices. The agent connects and holds position so it
can be dispatched; a few seconds later the subject starts transmitting, which
raises the alert. Then it waits for *you* to dispatch from the dashboard -
missions are never created automatically. Once dispatched it acknowledges,
drives to the subject and reports, leaving the mission for you to finalise.
"""
import json
import threading
import time
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from agents.models import AgentDevice, SubjectDevice

# The same path the agent notebook walks, ending at the subject.
AGENT_PATH = [
    (11.366309, 44.481247), (11.364764, 44.481675), (11.365193, 44.482441),
    (11.363906, 44.482839), (11.364335, 44.483543), (11.365665, 44.483329),
    (11.366695, 44.484890), (11.365580, 44.485380), (11.366095, 44.486391),
    (11.366223, 44.487829), (11.366138, 44.488687), (11.365623, 44.489115),
    (11.365108, 44.488472), (11.364550, 44.487676), (11.363734, 44.487676),
    (11.362833, 44.487983), (11.362018, 44.488289), (11.361460, 44.488442),
    (11.360601, 44.488840), (11.359743, 44.489146), (11.358928, 44.489452),
    (11.357941, 44.489758), (11.357563, 44.488766), (11.357906, 44.487358),
    (11.357906, 44.486317), (11.357906, 44.485582), (11.357211, 44.485319),
    (11.356653, 44.484860), (11.356267, 44.484370), (11.355323, 44.484462),
    (11.354422, 44.484737), (11.353520, 44.484737), (11.352877, 44.484829),
    (11.351975, 44.484860), (11.351117, 44.485074), (11.350087, 44.485196),
    (11.349315, 44.485319), (11.348328, 44.485503), (11.347426, 44.485748),
    (11.346396, 44.485992), (11.345452, 44.486513), (11.344937, 44.486911),
    (11.344551, 44.487278), (11.343907, 44.487523), (11.343307, 44.487646),
    (11.342534, 44.487768), (11.342362, 44.487187), (11.341504, 44.487309),
]

SUBJECT_AT = (44.487309, 11.341504)

SUCCESS = 1


def stamp():
    return str(datetime.now().replace(microsecond=0))


class Command(BaseCommand):
    help = 'Simulate a subject in distress and the agent sent to rescue them.'

    def add_arguments(self, parser):
        parser.add_argument('--base', default='ws://localhost:8000',
                            help='Where the websockets are. The default talks '
                                 'to daphne directly from inside the container.')
        parser.add_argument('--subject', default=None,
                            help='Subject device name. Defaults to the first one.')
        parser.add_argument('--agent', default=None,
                            help='Agent device name. Defaults to the first one.')
        parser.add_argument('--delay', type=float, default=8.0,
                            help='Seconds before the subject starts transmitting.')
        parser.add_argument('--interval', type=float, default=2.0,
                            help='Seconds between readings.')

    def handle(self, *args, **options):
        try:
            import websocket
        except ImportError:
            raise CommandError(
                'This needs websocket-client:\n'
                '    docker-compose exec web pip install websocket-client'
            )

        self.websocket = websocket
        self.base = options['base'].rstrip('/')
        self.interval = options['interval']
        self.stop = threading.Event()

        agent_device = self._device(AgentDevice, options['agent'], 'agent')
        subject_device = self._device(SubjectDevice, options['subject'], 'subject')

        self.stdout.write(self.style.MIGRATE_HEADING('\nSimulating a rescue'))
        self.stdout.write(f'  agent device   : {agent_device.name} ({agent_device.agent.name})')
        self.stdout.write(f'  subject device : {subject_device.name}')
        self.stdout.write(f'  centre to watch: {agent_device.agent.emergency_center}\n')

        agent = threading.Thread(target=self._run_agent, args=(agent_device,), daemon=True)
        agent.start()

        # Give the agent a moment to report a position: an agent that has never
        # reported one cannot be ranked by distance, so the alert would have
        # nobody to route to.
        time.sleep(options['delay'])

        subject = threading.Thread(target=self._run_subject, args=(subject_device,), daemon=True)
        subject.start()

        self.stdout.write(self.style.WARNING(
            '\n  The alert is on its way. Dispatch it from the dashboard -\n'
            '  nothing happens on its own. Ctrl-C to stop.\n'
        ))

        try:
            while agent.is_alive():
                agent.join(timeout=0.5)
        except KeyboardInterrupt:
            self.stdout.write('\n  stopping')
        finally:
            self.stop.set()
            time.sleep(self.interval)

    # ------------------------------------------------------------ devices --

    def _device(self, model, name, kind):
        queryset = model.objects.all()
        device = queryset.filter(name=name).first() if name else queryset.order_by('pk').first()

        if device is None:
            raise CommandError(
                f'No {kind} device found. Load the fixtures first:\n'
                '    python manage.py load_my_data data_new.json --exclude contenttypes'
            )
        return device

    def _open(self, path, device):
        socket = self.websocket.WebSocket()
        socket.connect(f'{self.base}{path}', header={'device': f'Resc {device.api_key}'})
        socket.settimeout(1)
        return socket

    def _say(self, who, message, style=None):
        line = f'  [{who}] {message}'
        self.stdout.write(style(line) if style else line)

    # -------------------------------------------------------------- agent --

    def _run_agent(self, device):
        socket = self._open('/ws/agent/send/', device)
        self._say('agent', 'connected')

        mission = {'id': None, 'driving': False, 'done': False}

        def listen():
            while not self.stop.is_set():
                try:
                    raw = socket.recv()
                except self.websocket.WebSocketTimeoutException:
                    continue
                except Exception:
                    return
                if not raw:
                    return

                message = json.loads(raw)

                if 'mission_assigned' in message:
                    mission['id'] = message['mission_assigned']['id']
                    self._say('agent', f"assigned mission {mission['id']} - acknowledging",
                              self.style.SUCCESS)
                    socket.send(json.dumps({
                        'type': 'mission_ack', 'mission_id': mission['id'],
                    }))
                    mission['driving'] = True
                    # A second mission needs reporting too. If the agent is
                    # already standing at the subject from the last one, there
                    # is no distance left to drive and it reports straight away.
                    mission['done'] = False

                elif 'mission_closed' in message:
                    self._say('agent', 'the centre closed the mission', self.style.SUCCESS)
                    mission['id'] = None
                    mission['driving'] = False

                elif 'error' in message:
                    self._say('agent', f"refused: {message['error']['code']}",
                              self.style.ERROR)

        threading.Thread(target=listen, daemon=True).start()

        step = 0
        longitude, latitude = AGENT_PATH[0]

        while not self.stop.is_set():
            # Only a mission moves the agent. Otherwise it holds wherever it is:
            # a crew that has just finished a rescue is still standing at the
            # subject, not back where it set off from.
            if mission['driving'] and step < len(AGENT_PATH):
                longitude, latitude = AGENT_PATH[step]
                step += 1
                if step == len(AGENT_PATH):
                    self._say('agent', 'arrived at the subject')

            try:
                socket.send(json.dumps({
                    'lat': latitude, 'lng': longitude, 'timestamp': stamp(),
                }))
            except Exception:
                return

            # Arrived, and not reported yet.
            if mission['driving'] and step >= len(AGENT_PATH) and not mission['done']:
                mission['done'] = True
                self._say('agent', 'reporting success - the centre still has to finalise it',
                          self.style.SUCCESS)
                socket.send(json.dumps({
                    'type': 'mission_report',
                    'mission_id': mission['id'],
                    'outcome': SUCCESS,
                }))

            time.sleep(self.interval)

    # ------------------------------------------------------------ subject --

    def _run_subject(self, device):
        socket = self._open('/ws/subject/send/', device)
        self._say('subject', 'transmitting - this is the distress signal',
                  self.style.ERROR)

        beat = 58
        while not self.stop.is_set():
            try:
                socket.send(json.dumps({
                    'lat': SUBJECT_AT[0],
                    'lng': SUBJECT_AT[1],
                    'heartrate': beat,
                    'timestamp': stamp(),
                }))
            except Exception:
                return

            beat = 58 + (beat - 56) % 12
            time.sleep(self.interval)

        socket.close()
