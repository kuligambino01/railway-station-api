from rest_framework.permissions import AllowAny
from rest_framework.routers import APIRootView, DefaultRouter

from station.views import (
    CrewViewSet,
    JourneyViewSet,
    OrderViewSet,
    RouteViewSet,
    StationViewSet,
    TrainTypeViewSet,
    TrainViewSet,
)


class PublicAPIRootView(APIRootView):
    permission_classes = [AllowAny]


class StationRouter(DefaultRouter):
    APIRootView = PublicAPIRootView


router = StationRouter()
router.register("stations", StationViewSet)
router.register("routes", RouteViewSet)
router.register("train-types", TrainTypeViewSet)
router.register("trains", TrainViewSet)
router.register("crew", CrewViewSet)
router.register("journeys", JourneyViewSet)
router.register("orders", OrderViewSet, basename="order")
urlpatterns = router.urls
