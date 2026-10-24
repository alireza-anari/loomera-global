"""Immutable reviewed booking-calendar dynamic UI keys.

Translation values live in the compiled fa/en/ar gettext catalogs.
These strings are display-only and must not be trusted server flashes.
"""
from types import MappingProxyType

BOOKING_JOURNEY_MESSAGE_IDS = MappingProxyType({
    "booking.calendar_guidance": "We try to keep this service on the same day. If not possible, you can choose another day.",
    "booking.choose_service_date_time": "Choose a suitable date and time for this service.",
    "booking.another_day_for_service": "Another day for this service",
    "booking.suggested": "Suggested",
    "booking.available_90_days": "Available and unavailable dates for this service over the next 90 days",
    "booking.default_still": "Default is still",
    "booking.default_still_suffix": "but you may choose another day.",
    "booking.default_same_day": "The default date for this service is",
    "booking.no_slot": "No appointment time",
    "booking.before_previous": "Before the previous service",
    "booking.no_room": "No available space",
    "booking.other_day_hint": "Choose another day, or move this service to another day if it cannot follow the previous service.",
    "booking.choose_other_day_action": "I will choose another day for this service",
    "booking.time_step": "Time selection step",
    "booking.no_time_short": "Time not selected",
    "booking.chosen_services": "Selected services",
    "booking.choose_other_day_if_needed": "If the same day is unavailable, choose another day for the next services.",
})
