"""Allowlisted static browser booking UI gettext identifiers.

Runtime only contains reviewed English source msgids; their fa/en/ar
translations live in the native compiled django.mo catalogs. Never
transport customer data, slot IDs, prices, account details or provider errors.
"""
from types import MappingProxyType

BOOKING_UI_MESSAGE_IDS = MappingProxyType({
    "booking.specialist": "Professional",
    "booking.any_professional": "Any available professional",
    "booking.service": "Service",
    "booking.awaiting_time": "Awaiting time",
    "booking.selected": "Selected",
    "booking.minutes": "minutes",
    "booking.toman": "toman",
    "booking.professional_selected": "Professional selected",
    "booking.continue_time": "Continue to time selection",
    "booking.services_remaining": "services remaining",
    "booking.professionals_selected": "professionals selected",
    "booking.services_without_professional": "services still need a professional",
    "booking.multi_service_booking": "Multi-service booking",
    "booking.same_day": "Same day",
    "booking.another_day": "Another day",
    "booking.step": "Service",
    "booking.of": "of",
    "booking.available_times": "Available appointment times",
    "booking.no_times": "No times available for this day",
    "booking.choose_day": "Choose a day to view available times",
    "booking.choose_date_time": "Choose a date and time to continue",
    "booking.continue_preview": "Continue to booking preview",
    "booking.save_new_time": "Save the new appointment time",
    "booking.confirm_next": "Confirm this service and continue",
    "booking.morning": "Morning",
    "booking.noon": "Midday",
    "booking.evening": "Evening",
    "booking.night": "Night",
    "booking.times": "times",
    "booking.no_time_selected": "No appointment time selected",
    "booking.summary": "Services and professionals",
    "booking.now_choose_hour": "Now choose the appointment time",
    "booking.please_choose_datetime": "Select a date and time to continue",
    "booking.open_jalali_calendar": "Open Jalali calendar",
    "booking.selectable_dates": "Available dates",
    "booking.slots_currently_available": "Only currently available times are shown.",
    "booking.no_picked_yet": "No appointment time has been selected yet.",
})
