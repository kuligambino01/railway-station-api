from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.backends import TokenBackend

from station.models import Crew, Journey, Order, Station, Ticket
from station.tests import create_journey


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
def test_api_root_is_public(client):
    response = client.get("/api/v1/")
    assert response.status_code == 200
    assert "journeys" in response.data


@pytest.fixture
def journey(db):
    return create_journey()


@pytest.fixture
def admin_client(client, db):
    user = get_user_model().objects.create_user("admin", is_staff=True)
    client.force_authenticate(user)
    return client


def test_filters_route_train_date_search_ordering(client, journey):
    later = Journey.objects.create(
        route=journey.route,
        train=journey.train,
        departure_time=journey.departure_time + timedelta(days=1),
        arrival_time=journey.arrival_time + timedelta(days=1),
    )
    url = "/api/v1/journeys/"
    params = {
        "route": journey.route_id,
        "train": journey.train_id,
        "date": journey.departure_time.date().isoformat(),
        "search": "Warszawa",
    }
    response = client.get(url, params)
    assert response.status_code == 200
    assert [row["id"] for row in response.data["results"]] == [journey.pk]
    response = client.get(url, {"ordering": "-departure_time"})
    assert [row["id"] for row in response.data["results"]] == [later.pk, journey.pk]
    assert client.get(url, {"train": 999999}).data["count"] == 0


@pytest.mark.parametrize(
    "params",
    [
        {"route": "abc"},
        {"train": "1.5"},
        {"source": "-1"},
        {"date": "tomorrow"},
        {"upcoming": "perhaps"},
    ],
)
def test_invalid_filters_return_400(client, journey, params):
    assert client.get("/api/v1/journeys/", params).status_code == 400


def test_public_list_hides_past_but_staff_can_inspect(client, journey, admin_client):
    journey.departure_time = timezone.now() - timedelta(hours=2)
    journey.arrival_time = timezone.now() - timedelta(hours=1)
    journey.save()
    anonymous = APIClient()
    assert anonymous.get("/api/v1/journeys/", {"upcoming": "false"}).data["count"] == 0
    assert admin_client.get("/api/v1/journeys/").data["count"] == 1
    assert (
        admin_client.get("/api/v1/journeys/", {"upcoming": "true"}).data["count"] == 0
    )


def test_pagination_and_station_search(client, journey):
    Station.objects.bulk_create(
        [
            Station(name=f"Test station {i:02d}", latitude=10, longitude=10)
            for i in range(23)
        ]
    )
    response = client.get(
        "/api/v1/stations/", {"search": "Test station", "ordering": "name"}
    )
    assert response.data["count"] == 23
    assert len(response.data["results"]) == 20
    assert response.data["next"] is not None
    page = client.get(
        "/api/v1/stations/", {"search": "Test station", "ordering": "name", "page": 2}
    )
    assert len(page.data["results"]) == 3
    assert page.data["results"][0]["name"] == "Test station 20"


def test_crew_relationship_can_be_updated(admin_client, journey):
    member = Crew.objects.create(first_name="Anna", last_name="Kowalska")
    response = admin_client.patch(
        f"/api/v1/journeys/{journey.pk}/", {"crew": [member.pk]}, format="json"
    )
    assert response.status_code == 200
    assert response.data["crew"] == [member.pk]
    assert list(member.journeys.values_list("pk", flat=True)) == [journey.pk]


def test_naive_timestamp_is_rejected(admin_client, journey):
    response = admin_client.patch(
        f"/api/v1/journeys/{journey.pk}/",
        {"departure_time": "2030-01-01T10:00:00"},
        format="json",
    )
    assert response.status_code == 400
    assert "departure_time" in response.data


def test_missing_journey_rolls_back_order(admin_client, journey):
    response = admin_client.post(
        "/api/v1/orders/",
        {
            "tickets": [
                {"journey": journey.pk, "cargo": 1, "seat": 1},
                {"journey": 999999, "cargo": 1, "seat": 2},
            ]
        },
        format="json",
    )
    assert response.status_code == 400
    assert not Order.objects.exists()
    assert not Ticket.objects.exists()


def test_successful_multi_ticket_order(admin_client, journey):
    response = admin_client.post(
        "/api/v1/orders/",
        {
            "tickets": [
                {"journey": journey.pk, "cargo": 1, "seat": 1},
                {"journey": journey.pk, "cargo": 2, "seat": 1},
            ]
        },
        format="json",
    )
    assert response.status_code == 201
    assert len(response.data["tickets"]) == 2
    assert Order.objects.count() == 1
    assert Ticket.objects.count() == 2


def test_old_public_key_cannot_forge_admin_token(client, db):
    admin = get_user_model().objects.create_user("admin", is_staff=True)
    payload = {
        "token_type": "access",
        "user_id": str(admin.pk),
        "jti": "regression",
        "exp": int((timezone.now() + timedelta(minutes=5)).timestamp()),
    }
    backend = TokenBackend(
        algorithm="HS256", signing_key="local-only-insecure-development-key-change-me"
    )
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {backend.encode(payload)}")
    assert client.get("/api/v1/crew/").status_code == 401


def test_list_query_count_does_not_grow_per_journey(
    client, journey, django_assert_num_queries
):
    Journey.objects.bulk_create(
        [
            Journey(
                route=journey.route,
                train=journey.train,
                departure_time=journey.departure_time + timedelta(days=i),
                arrival_time=journey.arrival_time + timedelta(days=i),
            )
            for i in range(1, 15)
        ]
    )
    # Page count, joined timetable with ticket counts, and crew prefetch.
    with django_assert_num_queries(3):
        response = client.get("/api/v1/journeys/")
    assert len(response.data["results"]) == 15
