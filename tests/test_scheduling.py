from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from rest_framework.test import APIClient

from station.models import Crew, Journey, Route, Train
from station.tests import create_journey


def payload(journey, **overrides):
    return {
        "route": journey.route_id,
        "train": journey.train_id,
        "departure_time": journey.departure_time.isoformat(),
        "arrival_time": journey.arrival_time.isoformat(),
        **overrides,
    }


@pytest.fixture
def setup(db):
    journey = create_journey()
    client = APIClient()
    client.force_authenticate(
        get_user_model().objects.create_user("staff", is_staff=True)
    )
    return client, journey


def test_same_train_overlap_rejected(setup):
    client, journey = setup
    response = client.post("/api/v1/journeys/", payload(journey), format="json")
    assert response.status_code == 409
    assert Journey.objects.count() == 1


def test_adjacent_journeys_are_allowed(setup):
    client, journey = setup
    response = client.post(
        "/api/v1/journeys/",
        payload(
            journey,
            departure_time=journey.arrival_time.isoformat(),
            arrival_time=(journey.arrival_time + timedelta(hours=1)).isoformat(),
        ),
        format="json",
    )
    assert response.status_code == 201


def test_crew_cannot_overlap_even_on_different_trains(setup):
    client, journey = setup
    member = Crew.objects.create(first_name="Anna", last_name="Crew")
    journey.crew.add(member)
    second_train = Train.objects.create(
        name="Other train",
        train_type=journey.train.train_type,
        cargo_num=1,
        places_in_cargo=10,
    )
    response = client.post(
        "/api/v1/journeys/",
        payload(journey, train=second_train.pk, crew=[member.pk]),
        format="json",
    )
    assert response.status_code == 409
    assert Journey.objects.count() == 1


def test_update_into_conflicting_time_is_rejected(setup):
    client, journey = setup
    second = Journey.objects.create(
        route=journey.route,
        train=journey.train,
        departure_time=journey.departure_time + timedelta(days=1),
        arrival_time=journey.arrival_time + timedelta(days=1),
    )
    response = client.patch(
        f"/api/v1/journeys/{second.pk}/", payload(journey), format="json"
    )
    assert response.status_code == 409
    second.refresh_from_db()
    assert second.departure_time > journey.arrival_time


def test_assigned_crew_cannot_be_deleted(setup):
    client, journey = setup
    member = Crew.objects.create(first_name="Anna", last_name="Crew")
    journey.crew.add(member)
    assert client.delete(f"/api/v1/crew/{member.pk}/").status_code == 400
    assert journey.crew.filter(pk=member.pk).exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("shared_resource", ["train", "crew"])
def test_concurrent_schedule_conflict_on_postgresql(shared_resource):
    if connection.vendor != "postgresql":
        pytest.skip("Requires PostgreSQL row locks and independent connections")
    template = create_journey()
    first_payload = payload(template)
    other_route = Route.objects.create(
        source=template.route.destination,
        destination=template.route.source,
        distance=template.route.distance,
    )
    # Separate routes prevent the route lock from serializing both requests.
    second_payload = payload(template, route=other_route.pk)
    if shared_resource == "crew":
        member = Crew.objects.create(first_name="Anna", last_name="Crew")
        other_train = Train.objects.create(
            name="Second train",
            train_type=template.train.train_type,
            cargo_num=1,
            places_in_cargo=10,
        )
        first_payload["crew"] = [member.pk]
        second_payload.update(train=other_train.pk, crew=[member.pk])
    template.delete()
    staff = get_user_model().objects.create_user("staff", is_staff=True)
    barrier = Barrier(2)

    def create(data):
        close_old_connections()
        try:
            client = APIClient()
            client.force_authenticate(staff)
            barrier.wait(timeout=10)
            return client.post("/api/v1/journeys/", data, format="json").status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(create, [first_payload, second_payload]))
    assert sorted(statuses) == [201, 409]
    assert Journey.objects.count() == 1
