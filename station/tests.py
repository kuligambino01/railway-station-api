from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from station.models import Journey, Order, Route, Station, Ticket, Train, TrainType


def create_journey():
    source = Station.objects.create(
        name="Warszawa Centralna", latitude=52.23, longitude=21.0
    )
    destination = Station.objects.create(
        name="Krakow Glowny", latitude=50.06, longitude=19.94
    )
    route = Route.objects.create(source=source, destination=destination, distance=293)
    train_type = TrainType.objects.create(name="Intercity")
    train = Train.objects.create(
        name="IC 100", cargo_num=2, places_in_cargo=10, train_type=train_type
    )
    return Journey.objects.create(
        route=route,
        train=train,
        departure_time=timezone.now() + timedelta(days=1),
        arrival_time=timezone.now() + timedelta(days=1, hours=3),
    )


class RailwayTests(APITestCase):
    def setUp(self):
        self.journey = create_journey()
        self.user = get_user_model().objects.create_user(
            "traveler", password="Unusual-pass-291!"
        )
        self.other = get_user_model().objects.create_user("other")
        self.admin = get_user_model().objects.create_user("admin", is_staff=True)
        self.client.force_authenticate(self.user)

    def book(self, seat=1, cargo=1, **extra):
        return self.client.post(
            "/api/v1/orders/",
            {
                "tickets": [{"journey": self.journey.pk, "cargo": cargo, "seat": seat}],
                **extra,
            },
            format="json",
        )

    def test_booking_and_owner_are_server_controlled(self):
        response = self.book(user=self.other.pk)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Order.objects.get().user, self.user)
        self.assertEqual(Ticket.objects.count(), 1)

    def test_duplicate_booking_returns_conflict(self):
        self.assertEqual(self.book().status_code, 201)
        self.assertEqual(self.book().status_code, 409)
        self.assertEqual(Order.objects.count(), 1)

    def test_failed_multi_ticket_order_is_atomic(self):
        self.book()
        response = self.client.post(
            "/api/v1/orders/",
            {
                "tickets": [
                    {"journey": self.journey.pk, "cargo": 1, "seat": 2},
                    {"journey": self.journey.pk, "cargo": 1, "seat": 1},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Ticket.objects.count(), 1)

    def test_repeated_seat_in_payload_is_rejected(self):
        ticket = {"journey": self.journey.pk, "cargo": 1, "seat": 1}
        response = self.client.post(
            "/api/v1/orders/", {"tickets": [ticket, ticket]}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.exists())

    def test_capacity_and_positive_seat_validation(self):
        for cargo, seat in [(0, 1), (1, 0), (3, 1), (1, 11), (-1, 1)]:
            with self.subTest(cargo=cargo, seat=seat):
                self.assertEqual(self.book(cargo=cargo, seat=seat).status_code, 400)
        self.assertFalse(Order.objects.exists())

    def test_empty_order_rejected(self):
        response = self.client.post("/api/v1/orders/", {"tickets": []}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_departed_journey_rejected(self):
        self.journey.departure_time = timezone.now() - timedelta(hours=1)
        self.journey.save()
        self.assertEqual(self.book().status_code, 400)

    def test_order_privacy_even_for_staff(self):
        order_id = self.book().data["id"]
        for user in [self.other, self.admin]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get("/api/v1/orders/").data["count"], 0)
            self.assertEqual(
                self.client.get(f"/api/v1/orders/{order_id}/").status_code, 404
            )

    def test_orders_cannot_be_modified_or_deleted(self):
        order_id = self.book().data["id"]
        self.assertEqual(
            self.client.delete(f"/api/v1/orders/{order_id}/").status_code, 405
        )
        self.assertEqual(
            self.client.patch(f"/api/v1/orders/{order_id}/", {}).status_code, 405
        )

    def test_anonymous_can_browse_but_not_book(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/v1/journeys/").status_code, 200)
        self.assertEqual(self.book().status_code, 401)
        self.assertEqual(self.client.get("/api/v1/crew/").status_code, 401)

    def test_only_admin_can_manage_railway_data(self):
        payload = {"name": "Gdansk", "latitude": 54.35, "longitude": 18.65}
        self.assertEqual(
            self.client.post("/api/v1/stations/", payload).status_code, 403
        )
        self.client.force_authenticate(self.admin)
        self.assertEqual(
            self.client.post("/api/v1/stations/", payload).status_code, 201
        )

    def test_invalid_coordinates(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            "/api/v1/stations/",
            {"name": "Invalid", "latitude": 91, "longitude": 181},
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_route_and_journey_times(self):
        self.client.force_authenticate(self.admin)
        station = self.journey.route.source_id
        self.assertEqual(
            self.client.post(
                "/api/v1/routes/",
                {"source": station, "destination": station, "distance": 10},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/v1/journeys/{self.journey.pk}/",
                {"arrival_time": self.journey.departure_time.isoformat()},
            ).status_code,
            400,
        )

    def test_booked_journey_and_used_train_are_immutable(self):
        self.book()
        self.client.force_authenticate(self.admin)
        self.assertEqual(
            self.client.patch(
                f"/api/v1/journeys/{self.journey.pk}/", {"crew": []}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/v1/trains/{self.journey.train_id}/", {"places_in_cargo": 1}
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.delete(f"/api/v1/journeys/{self.journey.pk}/").status_code,
            400,
        )

    def test_filtering_and_invalid_parameters(self):
        url = "/api/v1/journeys/"
        self.assertEqual(
            self.client.get(
                url, {"source": self.journey.route.source_id, "upcoming": "true"}
            ).data["count"],
            1,
        )
        self.assertEqual(
            self.client.get(url, {"destination": self.journey.route.source_id}).data[
                "count"
            ],
            0,
        )
        for params in [{"source": "abc"}, {"date": "tomorrow"}, {"upcoming": "maybe"}]:
            self.assertEqual(self.client.get(url, params).status_code, 400)

    def test_seat_map_and_remaining_capacity(self):
        self.book()
        seats = self.client.get(
            f"/api/v1/journeys/{self.journey.pk}/available-seats/"
        ).data
        self.assertEqual(len(seats), 20)
        self.assertFalse(seats[0]["available"])
        self.assertTrue(seats[1]["available"])
        self.assertEqual(
            self.client.get(f"/api/v1/journeys/{self.journey.pk}/").data[
                "available_seats"
            ],
            19,
        )

    def test_unique_seat_is_enforced_in_database(self):
        self.book()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Ticket.objects.create(
                order=Order.objects.get(), journey=self.journey, cargo=1, seat=1
            )

    def test_registration_jwt_and_profile(self):
        self.client.force_authenticate(None)
        payload = {
            "username": "new-user",
            "password": "Secure-example-42!",
            "is_staff": True,
        }
        response = self.client.post("/api/v1/auth/register/", payload)
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("password", response.data)
        self.assertFalse(get_user_model().objects.get(username="new-user").is_staff)
        tokens = self.client.post("/api/v1/auth/token/", payload).data
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(
            self.client.get("/api/v1/users/me/").data["username"], "new-user"
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]}
            ).status_code,
            200,
        )

    def test_weak_password_rejected(self):
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/register/", {"username": "weak", "password": "123"}
            ).status_code,
            400,
        )

    def test_browsable_api_and_schema(self):
        self.assertContains(
            self.client.get("/api/v1/journeys/", HTTP_ACCEPT="text/html"),
            "Journey List",
        )
        self.assertEqual(self.client.get("/api/schema/").status_code, 200)


@skipUnless(connection.vendor == "postgresql", "PostgreSQL row locking test")
class ConcurrentBookingTests(TransactionTestCase):
    def test_two_users_racing_for_same_seat(self):
        journey = create_journey()
        users = [get_user_model().objects.create_user(f"user-{i}") for i in range(2)]
        barrier = Barrier(2)

        def book(user):
            close_old_connections()
            try:
                client = APIClient()
                client.force_authenticate(user)
                barrier.wait(timeout=10)
                response = client.post(
                    "/api/v1/orders/",
                    {"tickets": [{"journey": journey.pk, "cargo": 1, "seat": 1}]},
                    format="json",
                )
                return response.status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(book, users))
        self.assertEqual(sorted(statuses), [201, 409])
        self.assertEqual(Ticket.objects.count(), 1)
        self.assertEqual(Order.objects.count(), 1)
