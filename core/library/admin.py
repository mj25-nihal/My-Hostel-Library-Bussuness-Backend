from django.contrib import admin
from .models import LibrarySeat, TimeSlot, LibraryBooking, LibraryMonthlyFee, LibraryMonthlyInvoice, \
    LibraryAvailableSwitchRequest, LibraryAvailableSwitchHistory, LibraryMutualSwitchRequest, LibraryMutualSwitchHistory


@admin.register(LibraryMonthlyInvoice)
class LibraryMonthlyInvoiceAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'student_name', 'seat_number',
        'month', 'amount', 'deposit', 'total', 'is_paid', 'generated_on', "invoice_expired"
    ]
    search_fields = ['booking__student__username', 'booking__seat__seat_number']
    list_filter = ['is_paid', 'month']

    def student_name(self, obj):
        return f"{obj.booking.student.first_name} {obj.booking.student.last_name}".strip()

    def seat_number(self, obj):
        return obj.booking.seat.seat_number if obj.booking.seat else None

    student_name.short_description = 'Student'
    seat_number.short_description = 'Seat'


@admin.register(LibrarySeat)
class LibrarySeatAdmin(admin.ModelAdmin):
    list_display = ['id', 'seat_number', 'description', 'is_booked']
    search_fields = ['seat_number']
    list_filter = ['is_booked']


@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ['id', 'start_time', 'end_time']


@admin.register(LibraryBooking)
class LibraryBookingAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'student', 'seat', 'seat_id_display',
        'purpose_of_joining', 'start_date', 'end_date', 'status', 'created_at'
    ]
    list_filter = ['status', 'start_date']
    search_fields = ['student__username', 'seat__seat_number']

    def seat_id_display(self, obj):
        return obj.seat.id

    seat_id_display.short_description = 'Seat ID'


# Register LibraryMonthlyFee model
@admin.register(LibraryMonthlyFee)
class LibraryMonthlyFeeAdmin(admin.ModelAdmin):
    list_display = ['id', 'monthly_fee', 'deposit_amount', 'effective_from', 'updated_at']


@admin.register(LibraryAvailableSwitchRequest)
class LibraryAvailableSwitchRequestAdmin(admin.ModelAdmin):
    list_display = ['id', 'student_name', 'current_seat', 'target_seat', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['booking__student__username', 'target_seat__seat_number', 'booking__seat__seat_number']

    def student_name(self, obj):
        return obj.booking.student.get_full_name()

    def current_seat(self, obj):
        return obj.booking.seat.seat_number if obj.booking and obj.booking.seat else None


@admin.register(LibraryAvailableSwitchHistory)
class LibraryAvailableSwitchHistoryAdmin(admin.ModelAdmin):
    list_display = ['id', 'booking', 'from_seat', 'to_seat', 'action', 'actor', 'created_at']
    list_filter = ['action', 'created_at']


@admin.register(LibraryMutualSwitchRequest)
class LibraryMutualSwitchRequestAdmin(admin.ModelAdmin):
    list_display = ['id', 'requester', 'partner', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['requester_booking__student__username', 'partner_booking__student__username']

    def requester(self, obj):
        return f"{obj.requester_booking.student.username} ({obj.requester_booking.seat})"

    def partner(self, obj):
        if obj.partner_booking:
            return f"{obj.partner_booking.student.username} ({obj.partner_booking.seat})"
        return "OPEN"


@admin.register(LibraryMutualSwitchHistory)
class LibraryMutualSwitchHistoryAdmin(admin.ModelAdmin):
    list_display = ['id', 'booking_a', 'booking_b', 'from_seat_a', 'to_seat_a', 'from_seat_b', 'to_seat_b', 'action',
                    'actor', 'created_at']
    list_filter = ['action', 'created_at']
