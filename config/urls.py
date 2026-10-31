from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from station.views import ProfileView, RegisterView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("station.urls")),
    path("api/v1/auth/register/", RegisterView.as_view(), name="register"),
    path("api/v1/users/me/", ProfileView.as_view(), name="profile"),
    path("api/v1/auth/token/", TokenObtainPairView.as_view(), name="token"),
    path(
        "api/v1/auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"
    ),
    path("api-auth/", include("rest_framework.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger",
    ),
]
