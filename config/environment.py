from django.core.exceptions import ImproperlyConfigured


def validate_secret(value):
    if not value or len(value) < 50 or value.startswith("django-insecure-"):
        raise ImproperlyConfigured(
            "SECRET_KEY must be a private random value of at least 50 characters. "
            "Set it in .env; see the README setup instructions."
        )
    if "change-this" in value or "change-me" in value or "change_this" in value:
        raise ImproperlyConfigured(
            "Replace the example SECRET_KEY with a random secret."
        )
    return value
