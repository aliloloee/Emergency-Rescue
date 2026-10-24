# **Emergency Rescue Platform**

A disaster-response backend for finding and reaching people trapped under rubble.

Wearable devices on trapped subjects transmit their location and vital signs. The system
works out who can reach them fastest, puts that decision in front of a human at the right
emergency centre, and follows the rescue through to the end — live, over WebSockets.

Built with Django, GeoDjango/PostGIS, Django Channels, Redis and Celery.

---

## **Table of contents**

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Architecture](#architecture)
- [Getting started](#getting-started)
- [Seeing it work](#seeing-it-work)
- [Running the tests](#running-the-tests)
- [Project layout](#project-layout)
- [Design notes](#design-notes)
- [Roadmap and known limitations](#roadmap-and-known-limitations)
- [License](#license)

---

## **What it does**

After an earthquake, a subject's device starts transmitting. From that moment:

1. The reading **is** the distress signal — there is no separate alarm to raise.
2. The system finds the **nearest free rescue agent** and alerts the emergency centre that
   owns that agent. Routing follows the agent rather than the centre, because what matters
   is who can get there, not whose office is closest.
3. That centre sees a **possible mission**: who is in trouble, where, their heart rate, and
   its own agents ranked by distance. **A person decides.** Missions are never created
   automatically.
4. The agent's device **acknowledges** the assignment — that is what starts the mission and
   begins recording their track.
5. The agent **reports** the outcome; the centre then **finalises** it. Two separate steps,
   so "the agent says it worked" and "the centre agrees" stay distinct facts.

An administrator has a separate, read-only view of every centre, agent, subject and mission
across all regions.

---

## **How it works**

### **The rules the system actually enforces**

These are the decisions that shape the code, and they are enforced in the service layer
rather than left to the interface:

| Rule | Why |
| --- | --- |
| A subject device only transmits during a disaster | Transmission is itself the distress signal; no thresholds, no triage rules |
| An agent device always transmits, but is only *recorded* while on a mission | Agents stay visible on the map without filling the database with idle driving |
| An agent belongs to exactly one centre, and only that centre may dispatch it | A centre is never offered an agent it cannot send |
| The centre owning the nearest free agent is alerted — and only that one | Not a race between centres, which would optimise for who answers fastest rather than who is closest |
| Missions are never created automatically | A rescue is a human decision |
| A mission starts when the device acknowledges, not when it is created | An assignment nobody received has not started |
| Completion is two-phase: the agent reports, the centre closes | The centre may disagree with the report |

### **The lifecycle**

```
subject device transmits
  -> DistressAlert raised (deduplicated per device: later readings refresh it)
  -> routed to the centre owning the nearest free agent
  -> centre picks one of ITS agents          => Mission, JUST_DEFINED
  -> agent's device acknowledges             => IN_PROGRESS, recording starts
  -> agent reports an outcome                => REPORTED
  -> centre finalises                        => CLOSED, agent released

at any point before the agent reports, the centre may instead call it off:
  -> centre aborts   => CLOSED, outcome ABORTED, agent released, and the alert
                        returns to the queue, because the subject is still trapped
```

Two consequences worth knowing:

- **A reading from a subject who already has a mission raises nothing.** They are still
  trapped and still transmitting, but a centre must not be re-alerted about someone already
  being helped.
- **An alert that cannot be routed waits rather than failing.** If no agent is free anywhere
  in the region, the alert stays unrouted and the device's *next* reading tries again. No
  scheduler, no retry queue — the device is already the heartbeat.

---

## **Architecture**

### **Data flow**

```
 device ──WebSocket──> Channels consumer ──> Redis list ──> Celery ──> PostGIS
                              │                                    (batched history)
                              ├──> last_location / last_seen  (one row, overwritten:
                              │                                this is what "nearest" reads)
                              └──> region group ──> every centre's live map
```

Readings are buffered in Redis and written in batches of a hundred, so a burst of traffic
does not become a burst of database writes. But a batch that lands every hundredth reading
cannot answer *"where is this device now"*, so each reading also overwrites a single
`last_location` column — and that is what the nearest-agent query reads.

### **WebSocket endpoints**

| Path | Who connects | Direction |
| --- | --- | --- |
| `ws/subject/send/` | A subject's device | Device → server |
| `ws/agent/send/` | An agent's device | Both — telemetry up, assignments down |
| `ws/center/recieve/` | A centre's map | Server → browser |
| `ws/center/panel/` | A centre's dispatch panel | Both — alerts and missions down, decisions up |
| `ws/root/panel/` | An administrator | Server → browser, read only |

Devices authenticate with an API key in a `device: Resc <key>` header. Browsers authenticate
with a JWT held in an HTTP-only cookie, refreshed transparently when it expires.

### **Pages**

| Path | Who |
| --- | --- |
| `/account/login/` | Everyone |
| `/agent/dashboard/` | Emergency centres — map and dispatch panel |
| `/agent/root/` | Administrators (`SUPER` profiles) — system-wide, read only |
| `/admin/` | Django admin, with Leaflet map widgets |
| `/docs/` | Swagger for the REST endpoints |

Signing in sends each account to the page it is allowed to open; the two panels refuse each
other's accounts.

---

## **Getting started**

Docker is the quickest path and needs nothing installed but Docker itself.

### **1. Configure `.env`**

```bash
cp .env.example .env
```

You only need to fill in `SECRET_KEY`. A working file looks like this:

```bash
SECRET_KEY=<generate one>
DEBUG=True
NAME=rescue
USER=postgres
PASSWORD=rescue12345
HOST=db
PORT=5432
REDIS_HOST=ram
DJANGO_SUPERUSER_EMAIL=admin@admin.com
DJANGO_SUPERUSER_FIRSTNAME=Admin
DJANGO_SUPERUSER_LASTNAME=Admin
DJANGO_SUPERUSER_PASSWORD=123
DOCKER_VOLUME1=pgdata
DOCKER_VOLUME2=static_volume
DJANGO_SETTINGS_MODULE=resc.settings.production
```

| Key | Meaning |
| --- | --- |
| `SECRET_KEY` | Django's secret key — generate your own |
| `DEBUG` | `True` for development, `False` otherwise |
| `NAME` / `USER` / `PASSWORD` / `HOST` / `PORT` | PostgreSQL connection |
| `REDIS_HOST` | Redis hostname (`ram` is the compose service name) |
| `DJANGO_SUPERUSER_*` | Used once, at first start, to create an admin |
| `DOCKER_VOLUME1` / `DOCKER_VOLUME2` | Volume names; keep these to match the compose file |
| `DJANGO_SETTINGS_MODULE` | `resc.settings.production` for Docker, `resc.settings.developement` otherwise |

> **Two things that will bite you.** The development settings module is spelled
> `developement` — the misspelling is the real module name. And the file must have **no
> byte-order mark**: with one, `SECRET_KEY` is not found and the image fails to build.
> (Windows PowerShell's `Set-Content -Encoding utf8` adds one.)

### **2. Start it**

```bash
docker volume create pgdata
docker volume create static_volume
docker network create app-network

docker-compose up --build -d
```

Five services come up: PostgreSQL/PostGIS, Redis, Django under daphne, a Celery worker and
nginx. The app is at **http://localhost/**.

### **3. Load the demo data**

```bash
docker-compose exec web python /app/resc/manage.py load_my_data data_new.json --exclude contenttypes
```

That gives you the region of **Bologna**, two emergency centres, seven agents with devices,
and five subject devices.

> **The admin account.** `init_admin` creates the superuser from your `.env`, but only when
> the user table is empty — and it runs at container start, *before* you load the fixtures.
> Loading them replaces the user rows, so that account no longer exists. Make yourself one:
>
> ```bash
> docker-compose exec web python /app/resc/manage.py createsuperuser
> ```

### **Running without Docker**

For working on the code. You will need Python 3.10, PostgreSQL with PostGIS, and Redis
running locally.

GeoDjango needs GDAL. On Windows that is the fiddly part —
[this guide](https://medium.com/@limeira.felipe94/gdal-configuration-and-installation-on-windows-for-django-projects-538171db5ccc)
covers it.

```bash
python -m venv venv
source venv/bin/activate          # Windows: .\venv\Scripts\activate
pip install -r requirements.txt

# in .env: DJANGO_SETTINGS_MODULE=resc.settings.developement
cd resc
python manage.py migrate
python manage.py runserver
```

Celery in a second terminal:

```bash
celery -A resc worker -l info              # Windows: add --pool=solo
```

The app is then at **http://localhost:8000/**.

---

## **Seeing it work**

### **The quickest way**

A management command plays both devices and walks a whole rescue, so you can watch the
dashboard while it happens. It needs nothing installed.

Sign in at **http://localhost/account/login/** as `emergency-center1@resc.com` / `123`, then:

```bash
docker-compose exec web python /app/resc/manage.py simulate
```

Watch the browser:

| When | What happens |
| --- | --- |
| immediately | An agent appears on the map and holds position |
| after ~8s | A subject starts transmitting — **Possible missions** turns to 1 |
| | Click the alert: the map centres on it, your agents re-sort nearest-first with distances |
| | Pick an agent, click **Dispatch** — the agent leaves the roster |
| ~2s later | **In progress**: that is the device acknowledging |
| ~90s | The agent drives to the subject, then **Reported** |
| | Choose success or failure and **Finalise** — the agent returns to the roster |

The command prints what each device is doing, so you can follow the terminal against the
screen. `Ctrl-C` stops it.

Useful flags: `--delay` (how long before the subject starts), `--interval` (seconds between
readings), `--subject` / `--agent` (device names).

### **Driving the devices by hand**

`communication-scripts/` holds two Jupyter notebooks, one per device type, which do the same
thing interactively. They need Python and Jupyter locally. **Run the agent notebook first** —
an agent that has not reported a position recently counts as offline and cannot be
dispatched, so the alert would have nowhere to go.

### **The administrator's view**

Sign in as a `SUPER` profile and you land on **/agent/root/**: every centre, every agent,
every mission, and — the thing only this view shows — alerts that could not be routed to
anybody because no agent was free.

---

## **Running the tests**

```bash
docker-compose exec web python /app/resc/manage.py test agents
```

73 tests, covering the dispatch rules directly and the WebSocket layer through Channels'
`WebsocketCommunicator` — no browser and no running server needed.

They pin the things that would be expensive to get wrong: that distances come back in metres
rather than degrees, that an alert follows the nearest *agent* rather than the nearest
centre, that repeated readings refresh one alert instead of raising dozens, that a centre
cannot touch another centre's agent or mission, that reporting does not close a mission, and
that both WebSocket close codes mean what the frontend thinks they mean.

---

## **Project layout**

```
resc/
├── accounts/     custom user model, JWT-in-cookie login
├── agents/       the domain: devices, alerts, missions, consumers, dispatch rules
│   ├── services.py    every dispatch rule, as plain functions over the database
│   ├── consumers.py   the five WebSocket endpoints
│   └── tests.py       73 tests
├── profiles/     profile ↔ region ↔ location ↔ type
├── resc/         settings (base / developement / production), asgi, celery
├── static/       dashboard JavaScript and CSS
└── templates/

communication-scripts/   device simulators as notebooks
```

The rules live in `agents/services.py` and know nothing about WebSockets, which is why they
can be tested directly and why the consumers stay thin.

---

## **Design notes**

A few decisions that are not obvious from the code:

**Distances are measured in metres, not degrees.** The location columns are PostGIS
`geography`. At plain SRID 4326 the distance functions return degrees, which looks plausible
and is wrong in a way a city-sized demo would never reveal.

**State is derived, not flagged.** "Is this agent on a mission" is answered by the mission
table and enforced by a partial unique constraint, rather than by a boolean somebody has to
remember to reset. The same applies to subjects: one open mission per subject device is a
database constraint, not a field.

**4001 and 4005 are different refusals.** A WebSocket closed with 4001 means "your token is
stale" and the browser refreshes and retries. 4005 means "this account, never" — retrying
would loop for ever. Also: a close code cannot be delivered on a connection that was never
accepted, so the consumers accept *then* close.

**The map shows what is live.** A marker fades once the server would consider that device
offline and disappears shortly after, using the same threshold the dispatcher uses. A rescued
subject's marker goes immediately — the device reads vital signs, so once it comes off them
there is nothing left to read.

---

## **Roadmap and known limitations**

The workflow is complete end to end: telemetry, alerting, routing, dispatch, acknowledgement,
reporting, finalising, and both dashboards.

What follows is deliberately out of scope for a first version, listed so it is not mistaken
for oversight:

- **No escalation when a centre does not respond.** An alert routed to a centre stays there;
  nothing times out or reassigns it. A mission a centre explicitly *calls off* does return
  the subject to the routing queue.
- **No acknowledgement timeout.** If a device never acknowledges, the mission stays open
  until a human calls it off.
- **Ranking is straight-line distance**, not travel time. The nearest agent as the crow flies
  is not always the quickest to arrive.
- **Dismissing an alert does not silence the device.** A device still transmitting raises a
  new alert — right for a long rescue, tedious for a false alarm.
- **Heart rate is carried and displayed but not acted on.** It does not influence triage.
- **The Redis client in the consumers is synchronous.** Fine at demonstration scale; a
  production deployment would want `redis.asyncio` so buffering cannot block the event loop.
- **One region.** Nothing assumes a single region, but the fixture only has Bologna.

---

## **License**

MIT — see [LICENSE](./LICENSE).
