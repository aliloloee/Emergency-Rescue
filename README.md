# **Emergency Rescue Platform**

## **Project Status** 🚧
**Currently in development**  
This project is actively being improved and expanded. New features and enhancements are in progress — see the [Roadmap](#roadmap) for what works today, what is being built, and what has deliberately been left for later.

---

## **Project Description**
The **Emergency Rescue Platform** is a backend system designed to support disaster response efforts by identifying and rescuing individuals trapped under rubble (e.g., post-earthquake scenarios). The platform integrates with custom devices capable of transmitting critical information, such as location and vital signs, even under rubble. This data is processed and routed to the emergency center best placed to respond, to facilitate timely rescue operations.

---

## **How It Works**
1. **Data Transmission**:  
   Custom devices broadcast signals containing:
   - Location data (latitude and longitude).
   - Vital signs (e.g., heart rate).

2. **Data Processing**:  
   Readings arrive over WebSockets, are buffered in Redis, and are written to a geospatial database in batches by a background worker.

3. **Dispatch**:  
   The system finds the nearest free rescue agent and alerts the emergency center that owns it, presenting a *possible mission* alongside that center's own agents ranked by distance. A person at the center decides — missions are never created automatically.

4. **Real-Time Updates**:  
   The agent's device acknowledges the assignment and later reports the outcome, which the center then finalises. Emergency centers follow every device and every mission as it happens.

---

## **How to Run the Project**

### **Configuring the `.env` File**

To run the project, you need to create a `.env` file from the provided `.env.example` file. This file contains essential configuration keys required by the application. Follow these steps:

1. **Create the `.env` File**:  
   Copy the `.env.example` file to a new file named `.env`:  
   ```bash
   cp .env.example .env
   ```

2. **Set the Configuration Keys**:
    `SECRET_KEY`:
    Add a secret key for your Django application. You can generate one using an online tool
    ```bash
    SECRET_KEY=your_secret_key_here
    ```
    `DEBUG`:
    Set this to True for development mode or False for production
    ```bash
    DEBUG=True
    ```

3. **PostgreSQL Configuration**:
    Provide the database credentials for PostgreSQL:
    ```bash
    NAME=your_database_name
    USER=your_database_user
    PASSWORD=your_database_password
    HOST=your_database_host
    PORT=5432  # Default PostgreSQL port
    ```

4. **Redis Configuration**:
    Set the Redis host name or IP address:
    ```bash
    REDIS_HOST=your_redis_host
    ```

5. **Django Superuser Configuration**:
    Define the default superuser's details (you can change these values as needed):
    ```bash
    DJANGO_SUPERUSER_EMAIL=admin@admin.com
    DJANGO_SUPERUSER_FIRSTNAME=Admin
    DJANGO_SUPERUSER_LASTNAME=Admin
    DJANGO_SUPERUSER_PASSWORD=123
    ```

6. **Docker Volumes**:
    Specify the names of the Docker volumes used for PostgreSQL data and static files. Use the same names provided here to ensure compatibility with the default `docker-compose` commands:
    ```bash
    DOCKER_VOLUME1=pgdata
    DOCKER_VOLUME2=static_volume
    ```

7. **Django Settings Module**:
    Set this key to switch between development and production environments:

    Use **resc.settings.development** for development mode, where all services (database, Redis, Django, Celery, etc.) are run manually.

    Use **resc.settings.production** for production mode, where `docker-compose` can be used to start all services quickly.

    ```bash
    DJANGO_SETTINGS_MODULE=resc.settings.development
    ```
    ```bash
    DJANGO_SETTINGS_MODULE=resc.settings.production
    ```

A sample `.env` file:
```bash
SECRET_KEY=
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
You only have to add the `SECRET_KEY` here.

### **Running the Application in Production Mode (with Docker)**

This mode is recommended if you want to quickly run the project and see the app in action. To run the app in production mode, you need to have Docker and Docker Compose installed, along with the required Docker images specified in the `docker-compose.yml` file.

Follow these steps to set up the app:

1. **Create Docker Volumes and Networks**:
    Create the required Docker volumes for data and static files, as well as a network for the app:
    ```bash
    docker volume create pgdata
    docker volume create static_volume
    docker network create app-network
    ```

2. **Start Docker Compose**:
    Build and start the services using Docker Compose:
    ```bash
    docker-compose up --build -d
    ```

3. **Optional but Recommended Commands**:
    Flush the Database (except Superuser): To clear the database while keeping the superuser, use the following command
    ```bash
    docker-compose exec web python /app/resc/manage.py flush_except_superuser
    ```
    Load Fixtures: To load initial data into the database, run the following command, replacing `data_new.json` with the fixture file you want to load
    ```bash
    docker-compose exec web python /app/resc/manage.py load_my_data data_new.json --exclude contenttypes
    ```

### **Running the Application in Development Mode**

Running the application in development mode is recommended for those who wish to modify or expand its functionality. In this mode, you must manually configure and start each service individually.

1. **Configure PostgreSQL with PostGIS Extension**:  
   As the application utilizes GeoDjango, it is necessary to create the `PostGIS` extensions for your PostgreSQL database.

   - **For Windows Users**: Ensure that the GDAL library is correctly configured, as it is required for GeoDjango. Detailed instructions can be found in this [Guide](https://medium.com/@limeira.felipe94/gdal-configuration-and-installation-on-windows-for-django-projects-538171db5ccc).

2. **Initialze Redis Database**

3. **Run the Django Application**:  
   Ensure you have installed a tool for creating isolated Python environments. We recommend using `virtualenv`, which can be installed using the following command:  
   ```bash
   pip install virtualenv
   ```

    - **Create the Virtual Environment**:
        ```bash
        virtualenv venv
        ```
    - **Install the Requirements**:
        ```bash
        pip install -r requirements.txt
        ```
    - **Activate the virtual environment**:
        For windows users:
        ```bash
        .\venv\Scripts\Activare
        ```
        For linux users:
        ```bash
        source venv/bin/activate
        ```
    - **Run the App**:
        Navigate to the directory containing the *manage.py* file and execute:
        ```bash
        python manage.py runserver
        ```

4. **Run the Celery Application**:
    In another terminal, activate the virtual environment and navigate to the directory containing the *manage.py* file.
    For windows users:
    ```bash
    celery -A resc worker -l info --pool=solo
    ```
    For linux users:
    ```bash
    celery -A resc worker --loglevel=info
    ```

5. **Optional but Recommended Commands**:
    Flush the Database (except Superuser): To clear the database while keeping the superuser, use the following command
    ```bash
    python manage.py flush_except_superuser
    ```
    Load Fixtures: To load initial data into the database, run the following command, replacing `data_new.json` with the fixture file you want to load
    ```bash
    python manage.py load_my_data data_new.json --exclude contenttypes
    ```

---

## **What you will see**

If you have done everything correctly, in *production* mode the base url will be *http://localhost/* and in *developement* mode, *http://localhost:8000/*.

### **Admin page**:

When the application is up and running, you can go to the url */admin/* and log into the admin panel. If you have done the recommended loading of fixtures, you can expect to see the admin panel as below:

> **A note on the admin credentials.** The superuser described in your `.env` is created by the `init_admin` command, which only runs when the user table is empty — and it runs at container start, *before* you load the fixtures. Loading `data_new.json` then replaces the user rows, so that superuser no longer exists. If you loaded the fixtures, create an admin account for yourself with:
>
> ```bash
> docker-compose exec web python /app/resc/manage.py createsuperuser
> ```
>
> If you skip the fixtures, the `.env` credentials work exactly as described above.

![Admin Panel](./readme/admin/overview.png "Admin Panel")
Admin Panel


![Instance Added by Fixture to SubjectDevice Model](./readme/admin/subject-device-instance.png "Instance Added by Fixture to SubjectDevice Model")
Instance added by fixture to SubjectDevice model

![Details of a SubjectDevice Instance](./readme/admin/subject-device-details.png "Details of a SubjectDevice Instance")
Details of a SubjectDevice Instance

### **Emergency Center Dashboard**

The Emergency Center Dashboard allows emergency centers to monitor all operations in real-time. This includes data sent by the devices of agents (e.g., ambulances) and subjects in need of help (e.g., individuals under rubble).  

To view how data is monitored:  
1. Navigate to the login page at `account/login/`.  
2. Log in using the following credentials:  
   - **Username:** emergency-center1@resc.com  
   - **Password:** 123  
3. After logging in, you will be redirected to a real-time map of the city of **Bologna** at `agent/dashboard/`. This dashboard provides a comprehensive overview of all monitored activities and locations.

<figure>
  <img src="./readme/dashboard/icons/agent.png" alt="Alt text" width="50">
  <figcaption>Icon used for Agents</figcaption>
  <br>
  <img src="./readme/dashboard/icons/subject.png" alt="Alt text" width="50">
  <figcaption>Icon used for Subjects</figcaption>
  <br>
  <img src="./readme/dashboard/icons/star.png" alt="Alt text" width="50">
  <figcaption>Icon used for Emergency-Centers</figcaption>
</figure>

To simulate the functionality of the devices, two scripts have been created and are located in the `communication-scripts` folder:  
- One script mimics the devices used by agents (e.g., ambulances).  
- The other script mimics the devices used by subjects in need of assistance (e.g., individuals under rubble).  

These scripts communicate directly with the backend system, emulating real-world data transmission. The `GIF` below demonstrates what the user *Emergency-center 1* sees on their dashboard panel. 

![Details of a SubjectDevice Instance](./readme/dashboard/ezgif.com-speed.gif "Details of a SubjectDevice Instance")

---

## **Roadmap**

### **Working today**

- **Device telemetry.** Subject and agent devices stream location (and, for subjects, heart rate) over WebSockets, authenticated per device with an API key. Readings are buffered in Redis and written to PostgreSQL in batches by a Celery worker, so a burst of traffic does not become a burst of database writes.
- **Live regional map.** An emergency center sees every device in its own region move in real time, over a Django Channels feed scoped to that region.
- **Authentication and authorisation.** Devices authenticate with an API key; browsers with a JWT held in an HTTP-only cookie, refreshed transparently. A center can only ever subscribe to its own region, and only accounts of the emergency-center type can subscribe at all.
- **Agent availability feed.** A separate socket publishes which agents are free, so a dispatch panel can be built against it.

### **In progress — automated dispatch**

The feature this platform exists for: turning a distress signal into a rescue.

A subject device only transmits when something has gone wrong, so transmission *is* the distress signal. The system finds the nearest free rescue agent, and alerts **the emergency center that owns that agent** — routing follows the agent rather than the center, because the point is to reach the subject quickly. That center sees a *possible mission*, together with its own available agents ranked by distance, and a human decides. Missions are never created automatically.

Once an agent is assigned, their device acknowledges the assignment, which is what puts the mission in progress and starts recording their track. When the work is done the agent reports the outcome, and the center then finalises the mission — two separate steps, so that "the agent says it worked" and "the center agrees" stay distinct facts.

**Status:** the domain rules are implemented and covered by 42 tests — nearest-agent ranking, alert deduplication and routing, mission creation with ownership checks, and the full lifecycle including a center's ability to call a mission off. What remains is connecting them to the WebSocket layer and building the panels.

### **Planned**

- **Emergency center dispatch panel** — the possible-mission list, ranked agents, and the dispatch and finalise controls.
- **Root panel** — a system-wide view, for an administrator rather than a single center, of all centers, agents, subjects and missions.
- **A downlink to agent devices**, so assignments can be pushed to them and acknowledged.
- **Updated simulation notebooks**, so the scripts in `communication-scripts/` can acknowledge assignments and report outcomes.

### **Known limitations**

Deliberate scope choices for a first version, listed so they are not mistaken for oversights:

- **No escalation when a center does not respond.** An alert routed to a center stays there; nothing times out or reassigns it. (A mission a center explicitly *calls off* does return the subject to the routing queue.)
- **No acknowledgement timeout.** If an agent's device never acknowledges, the mission stays open until a human intervenes.
- **Ranking is straight-line distance**, not travel time, so the nearest agent as the crow flies may not be the quickest to arrive.
- **Dismissing an alert does not silence the device.** If a center dismisses a false alarm and the device keeps transmitting, a new alert is raised — correct for a long rescue, unhelpful for a false alarm.
- **Heart rate is recorded and displayed but not acted on.** It does not yet influence triage or prioritisation.
- **The Redis client in the consumers is synchronous.** Fine at demonstration scale; a production deployment would want `redis.asyncio` so that buffering cannot block the event loop.