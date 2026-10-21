"""
A process that serves no requests, such as ``manage.py shell`` or a Celery worker,
doesn't import the viewsets that say what a write affects. Its writes change ETags
all the same.
"""

import os
import subprocess
import sys

from django.db import connection
from django.test import Client

import pytest

from testapp.models import Folder, Sheet

from .etags import ServedBodies, assert_served_etags_match

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures("etag_api"),
]

SHELL = """
import sys

import django

django.setup()

from django.conf import settings
from django.db import transaction

from testapp.models import Sheet

settings.ROOT_URLCONF = "testapp.etag_urls"
assert "testapp.etag_viewsets" not in sys.modules, "the shell imported the viewsets"
with transaction.atomic():
    sheet = Sheet.objects.get()
    sheet.title = "b"
    sheet.save()
"""


def run_in_a_shell(script: str) -> None:
    env = {**os.environ, "PGDATABASE": connection.settings_dict["NAME"]}
    subprocess.run([sys.executable, "-c", script], env=env, check=True)


def test_a_write_in_a_shell(client: Client):
    folder = Folder.objects.create(name="a", code="a")
    Sheet.objects.create(folder=folder, title="a", position=0)
    served = ServedBodies()
    assert_served_etags_match(client, served)

    run_in_a_shell(SHELL)

    assert_served_etags_match(client, served)
