# Generated by Django 5.0.4 on 2024-07-31 13:32

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agents', '0003_lifedata'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Agent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, verbose_name='name')),
                ('busy', models.BooleanField(default=False, verbose_name='Agent is busy')),
                ('created', models.DateTimeField(auto_now_add=True, verbose_name='Created')),
                ('updated', models.DateTimeField(auto_now=True, verbose_name='Updated')),
                ('emergency_center', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='agents', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Agent',
                'verbose_name_plural': 'Agents',
                'ordering': ('created',),
            },
        ),
        migrations.CreateModel(
            name='Mission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.PositiveSmallIntegerField(choices=[(1, 'IN_PROGRESS'), (2, 'SUCCESS'), (3, 'FAILURE')], default=1, verbose_name='Status')),
                ('agent_records', models.JSONField(default=list, verbose_name='Agent records')),
                ('subject_records', models.JSONField(default=list, verbose_name='Subject records')),
                ('created', models.DateTimeField(auto_now_add=True, verbose_name='Created')),
                ('updated', models.DateTimeField(auto_now=True, verbose_name='Updated')),
                ('agent', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='missions', to='agents.agent')),
                ('subject', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='missions', to=settings.AUTH_USER_MODEL, verbose_name='Alive subject')),
            ],
            options={
                'verbose_name': 'Mission',
                'verbose_name_plural': 'Missions',
                'ordering': ('created',),
            },
        ),
    ]
