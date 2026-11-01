from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from station.models import Station
from station.views import StationViewSet


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["patch", "delete"])
def test_record_removed_between_reads_returns_404(method):
    station = Station.objects.create(name="Station", latitude=0, longitude=0)
    client = APIClient()
    client.force_authenticate(
        get_user_model().objects.create_user("staff", is_staff=True)
    )
    original_get_object = StationViewSet.get_object

    def get_then_remove(view):
        instance = original_get_object(view)
        Station.objects.filter(pk=instance.pk).delete()
        return instance

    # Simulate another request deleting the row before the locked read.
    with patch.object(StationViewSet, "get_object", get_then_remove):
        response = getattr(client, method)(
            f"/api/v1/stations/{station.pk}/", {"name": "Updated"}, format="json"
        )
    assert response.status_code == 404
