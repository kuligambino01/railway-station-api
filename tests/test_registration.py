import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@pytest.mark.django_db
@pytest.mark.parametrize("username", ["K", "\u212a"])
def test_equivalent_username_is_rejected(username):
    get_user_model().objects.create_user("K")
    response = APIClient().post(
        "/api/v1/auth/register/",
        {"username": username, "password": "Another-unusual-password-425!"},
        format="json",
    )
    assert response.status_code == 400
    assert "username" in response.data
    assert get_user_model().objects.count() == 1


@pytest.mark.django_db
def test_username_length_is_checked_after_normalization():
    response = APIClient().post(
        "/api/v1/auth/register/",
        {"username": "\ufb03" * 51, "password": "Another-unusual-password-425!"},
        format="json",
    )
    assert response.status_code == 400
    assert "username" in response.data
    assert not get_user_model().objects.exists()


@pytest.mark.django_db
def test_username_is_normalized_on_registration():
    response = APIClient().post(
        "/api/v1/auth/register/",
        {"username": "\u212a", "password": "Another-unusual-password-425!"},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["username"] == "K"
    assert get_user_model().objects.get().username == "K"
