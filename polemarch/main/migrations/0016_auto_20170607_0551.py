# -*- coding: utf-8 -*-
# Generated by Django 1.10.7 on 2017-06-07 05:51
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0015_auto_20170530_0109'),
    ]

    operations = [
        migrations.CreateModel(
            name='PeriodicTask',
            fields=[
                ('id', models.AutoField(max_length=20, primary_key=True, serialize=False)),
                ('playbook', models.CharField(max_length=256)),
                ('schedule', models.CharField(max_length=4096)),
                ('type', models.CharField(max_length=10)),
                ('inventory', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='periodic_tasks', related_query_name='periodic_tasks', to='main.Inventory')),
                ('project', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='periodic_tasks', related_query_name='periodic_tasks', to='main.Project')),
            ],
            options={
                'default_related_name': 'periodic_tasks',
            },
        ),
        migrations.AddField(
            model_name='typespermissions',
            name='periodic_tasks',
            field=models.ManyToManyField(blank=True, null=True, related_name='related_objects', related_query_name='related_objects', to='main.PeriodicTask'),
        ),
    ]
