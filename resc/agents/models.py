from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.auth import get_user_model
from django.conf import settings

from agents import utils
from agents.utils import CustomJSONField

User = get_user_model()


class BaseModel(models.Model) :

    created = models.DateTimeField(auto_now_add=True, verbose_name=_('Created'))
    updated = models.DateTimeField(auto_now=True, verbose_name=_('Updated'))

    class Meta :
        abstract = True


class Point(BaseModel) :
    name = models.CharField(verbose_name=_('name'), max_length=100)
    location = models.PointField(verbose_name=_('location'), srid=4326)

    class Meta :
        verbose_name = _('Point')
        verbose_name_plural = _('Points')
        ordering = ('created',)

    def __str__(self):
        return self.name


class Region(BaseModel):
    name = models.CharField(verbose_name=_('name'), max_length=100)
    description = models.CharField(verbose_name=_('description'), max_length=500)
    polygon = models.PolygonField(verbose_name=_('polygon'), srid=4326)

    class Meta:
        verbose_name = _('Region')
        verbose_name_plural = _('Regions')
        ordering = ('created',)

    def __str__(self):
        return self.name


class Agent(BaseModel):
    name = models.CharField(max_length=100, verbose_name=_("name"))
    emergency_center = models.ForeignKey(User, on_delete=models.CASCADE, related_name="agents")
    busy = models.BooleanField(default=False, verbose_name=_("Agent is busy"))


    class Meta:
        verbose_name = _('Agent')
        verbose_name_plural = _('Agents')
        ordering = ('created',)

    def __str__(self):
        return self.name


class Device(BaseModel) :
    api_key = models.CharField(
                    max_length=100, default=utils.generate_api_key, 
                    blank=True, verbose_name=_('API Key')
                    )
    name = models.CharField(
                    max_length=100,
                    verbose_name=_('Device name')
                    )

    class Meta :
        abstract = True


class LocatableDevice(Device) :
    """
    A device that reports where it is.

    The readings themselves are batched into SubjectRecords/AgentRecords by way of
    Redis, which makes them useless for answering "where is this device now" - the
    batch only lands every hundredth reading, and it lands as JSON rather than as
    geometry. These two fields are the current position, overwritten on every
    reading, and they are what the nearest-agent query actually reads.

    geography=True so that distances come back in metres. A plain geometry field at
    SRID 4326 measures in degrees, which is wrong in a way that a city-sized demo
    would never reveal. GeoDjango indexes spatial fields by default, so declaring
    the field is enough to get the GiST index.
    """
    last_location = models.PointField(
                    srid=4326, geography=True, blank=True, null=True,
                    verbose_name=_('Last known location')
                    )
    last_seen = models.DateTimeField(
                    blank=True, null=True,
                    verbose_name=_('Last transmission')
                    )

    class Meta :
        abstract = True


class SubjectDevice(LocatableDevice) :
    subject = models.ForeignKey(
                    User, on_delete=models.CASCADE, blank=True, null=True,
                    related_name='devices', verbose_name=_('Subject')
                    )

    class Meta :
        unique_together = ('subject', 'name', )
        verbose_name = _('Subject device')
        verbose_name_plural = _('Subject devices')
        ordering = ('created',)

    def __str__(self):
        return f'Subject device: {self.name}'


class AgentDevice(LocatableDevice) :
    agent = models.ForeignKey(
                    Agent, on_delete=models.CASCADE,
                    related_name='devices', verbose_name=_('Agent')
                    )

    class Meta :
        unique_together = ('agent', 'name', )
        verbose_name = _('Agent device')
        verbose_name_plural = _('Agent devices')
        ordering = ('created',)

    def __str__(self):
        return f'Agent device: {self.name}'


class SubjectRecords(BaseModel) :
    device = models.ForeignKey(
                    SubjectDevice, on_delete=models.CASCADE,
                    related_name='records', verbose_name=_('Device')
                    )

    data = CustomJSONField(required_keys=settings.SUBJECT_REQUIRED_KEYS, default=list)

    class Meta :
        verbose_name = _('Subject Record')
        verbose_name_plural = _('Subject Records')
        ordering = ('created',)

    def __str__(self):
        return f'Subject record with device {self.device.name}'


class AgentRecords(BaseModel) :
    device = models.ForeignKey(
                    AgentDevice, on_delete=models.CASCADE,
                    related_name='records', verbose_name=_('Device')
                    )
    # An agent device transmits continuously so that it stays visible on the map,
    # but only what it sends while on a mission is recorded. The mission is what
    # that recording belongs to; it is nullable only so the field can be added to
    # the rows that already exist.
    mission = models.ForeignKey(
                    'Mission', on_delete=models.CASCADE, blank=True, null=True,
                    related_name='records', verbose_name=_('Mission')
                    )

    data = CustomJSONField(required_keys=settings.AGENT_REQUIRED_KEYS, default=list)

    class Meta :
        verbose_name = _('Agent Record')
        verbose_name_plural = _('Agent Records')
        ordering = ('created',)

    def __str__(self):
        return f'Agent record with device {self.device.name}'


class DistressAlert(BaseModel) :
    """
    A "possible mission": a subject device is transmitting, which by itself means
    the subject is in trouble.

    Missions are never created automatically - this is raised for a human at an
    emergency center to act on. It exists as a row rather than as a passing
    websocket message for three reasons: a device in distress transmits every few
    seconds and those readings must collapse into one alert; an alert raised while
    nobody is logged in must survive; and the root panel needs to show what was
    detected, not only what was acted on.

    emergency_center is the center that owns the nearest free agent, which is how
    alerts are routed. It stays null when no agent was free anywhere in the region;
    the next reading from the device retries the routing.
    """
    subject_device = models.ForeignKey(
                            SubjectDevice, on_delete=models.CASCADE,
                            related_name='alerts', verbose_name=_('Subject device')
                            )
    emergency_center = models.ForeignKey(
                            User, on_delete=models.SET_NULL, blank=True, null=True,
                            related_name='alerts', verbose_name=_('Alerted emergency center')
                            )
    location = models.PointField(
                            srid=4326, geography=True,
                            verbose_name=_('Location of the subject')
                            )
    status = models.PositiveSmallIntegerField(
                            choices=utils.AlertStatus.choices, default=utils.AlertStatus.UNROUTED,
                            verbose_name=_('Status')
                            )
    first_seen = models.DateTimeField(verbose_name=_('First transmission'))
    last_seen = models.DateTimeField(verbose_name=_('Latest transmission'))

    class Meta :
        verbose_name = _('Distress alert')
        verbose_name_plural = _('Distress alerts')
        ordering = ('-last_seen',)
        constraints = [
            # Deduplication, enforced by the database rather than by whoever
            # remembers to check first: a device that is already the subject of an
            # undecided alert cannot raise a second one.
            models.UniqueConstraint(
                fields=('subject_device',),
                condition=models.Q(status__in=utils.AlertStatus.open_statuses()),
                name='one_open_alert_per_subject_device',
            ),
        ]

    def __str__(self):
        return f'Distress alert from {self.subject_device.name}'


class Mission(BaseModel):
    """
    A rescue, confirmed by a human at an emergency center.

    status is the lifecycle, outcome is what happened - see MissionStatus. The two
    are separate because the agent reports an outcome and the center then closes
    the mission, possibly disagreeing with that report.
    """
    alert = models.ForeignKey(
                            DistressAlert, on_delete=models.PROTECT, blank=True, null=True,
                            related_name='missions', verbose_name=_('Distress alert')
                            )
    agent = models.ForeignKey(Agent, on_delete=models.PROTECT, related_name="missions")
    emergency_center = models.ForeignKey(
                            User, on_delete=models.PROTECT,
                            related_name='center_missions', verbose_name=_('Emergency center')
                            )
    subject_device = models.ForeignKey(
                            SubjectDevice, on_delete=models.PROTECT,
                            related_name='missions', verbose_name=_('Subject device')
                            )
    # The device is what reports, and it may not be registered to anybody, so the
    # subject is the optional half of the pair rather than the required one.
    subject = models.ForeignKey(
                            User, on_delete=models.PROTECT, blank=True, null=True,
                            related_name="missions", verbose_name=_("Alive subject")
                            )
    # Where the subject was when the mission was defined. This cannot be derived
    # from the subject: the only location a User has is their profile address,
    # which is where they live, not where they are trapped.
    location = models.PointField(
                            srid=4326, geography=True,
                            verbose_name=_('Location of the subject')
                            )
    status = models.PositiveSmallIntegerField(
                            choices=utils.MissionStatus.choices, default=utils.MissionStatus.JUST_DEFINED,
                            verbose_name=_('Status')
                            )
    outcome = models.PositiveSmallIntegerField(
                            choices=utils.MissionOutcome.choices, blank=True, null=True,
                            verbose_name=_('Outcome')
                            )
    acknowledged_at = models.DateTimeField(blank=True, null=True, verbose_name=_('Acknowledged by agent'))
    reported_at = models.DateTimeField(blank=True, null=True, verbose_name=_('Reported by agent'))
    closed_at = models.DateTimeField(blank=True, null=True, verbose_name=_('Closed by center'))
    archived = models.BooleanField(default=False, verbose_name=_("Mission is archived"))

    class Meta:
        verbose_name = _('Mission')
        verbose_name_plural = _('Missions')
        ordering = ('created',)
        constraints = [
            models.UniqueConstraint(
                fields=('agent',),
                condition=models.Q(status__in=utils.MissionStatus.open_statuses()),
                name='one_open_mission_per_agent',
            ),
            # This is what replaces SubjectDevice.occupied: the same fact, as a
            # constraint the database enforces rather than a boolean that has to be
            # kept in step by hand.
            models.UniqueConstraint(
                fields=('subject_device',),
                condition=models.Q(status__in=utils.MissionStatus.open_statuses()),
                name='one_open_mission_per_subject_device',
            ),
        ]

    def __str__(self):
        return f'Mission by agent {self.agent.name}'


class Route(BaseModel) :
    """
    This model has no use in real-world. It is only added to draw simulation movement of the agents on the map,
    and get their coordinates for communication scripts. 
    """
    name = models.CharField(max_length=100)
    path = models.MultiLineStringField()

    class Meta:
        verbose_name = _('Route')
        verbose_name_plural = _('Routes')
        ordering = ('created',)

    def __str__(self):
        return self.name