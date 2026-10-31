from django.contrib import admin

from station.models import (
    Crew,
    Journey,
    Order,
    Route,
    Station,
    Ticket,
    Train,
    TrainType,
)


@admin.register(Station, Route, TrainType, Train, Crew, Journey)
class RailwayAdmin(admin.ModelAdmin):
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False


@admin.register(Order, Ticket)
class ReservationAdmin(RailwayAdmin):
    pass
