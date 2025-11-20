from django.contrib import admin
from .models import HostelRoom, HostelBed, HostelBooking, HostelMonthlyFee, HostelMonthlyInvoice, \
    HostelAvailableSwitchRequest, HostelAvailableSwitchHistory, HostelMutualSwitchRequest, HostelMutualSwitchHistory

admin.site.register(HostelRoom)


# admin.site.register(HostelBed)
@admin.register(HostelBed)
class HostelBedAdmin(admin.ModelAdmin):
    list_display = ['id', 'room', 'bed_number', 'description', 'is_booked']
    search_fields = ['bed_number']


# admin.site.register(HostelBooking)
@admin.register(HostelMonthlyInvoice)
class HostelMonthlyInvoiceAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'student_name', 'room_number', 'bed_number',
        'month', 'amount', 'deposit', 'total', 'is_paid', 'generated_on', "invoice_expired",
    ]
    search_fields = ['booking__student__username', 'booking__bed__bed_number']
    list_filter = ['is_paid', 'month']

    def student_name(self, obj):
        return f"{obj.booking.student.first_name} {obj.booking.student.last_name}".strip()

    def room_number(self, obj):
        return obj.booking.bed.room.room_number if obj.booking.bed else None

    def bed_number(self, obj):
        return obj.booking.bed.bed_number if obj.booking.bed else None

    student_name.short_description = 'Student'
    room_number.short_description = 'Room'
    bed_number.short_description = 'Bed'


@admin.register(HostelBooking)
class HostelBookingAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'student', 'bed', 'bed_id_display',
        'purpose_of_joining', 'start_date', 'end_date', 'status', 'created_at'
    ]
    list_filter = ['status', 'start_date']
    search_fields = ['student__username', 'bed__bed_number']

    def bed_id_display(self, obj):
        return obj.bed.id

    bed_id_display.short_description = 'Bed ID'


# Register HostelMonthlyFee model
@admin.register(HostelMonthlyFee)
class HostelMonthlyFeeAdmin(admin.ModelAdmin):
    list_display = ['id', 'monthly_fee', 'deposit_amount', 'effective_from', 'updated_at']


@admin.register(HostelAvailableSwitchRequest)
class HostelAvailableSwitchRequestAdmin(admin.ModelAdmin):
    list_display = ['id', 'student_name', 'current_bed', 'target_bed', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['booking__student__username', 'target_bed__bed_number', 'booking__bed__bed_number']

    def student_name(self, obj):
        return obj.booking.student.get_full_name()

    def current_bed(self, obj):
        return obj.booking.bed.bed_number if obj.booking and obj.booking.bed else None


@admin.register(HostelAvailableSwitchHistory)
class HostelAvailableSwitchHistoryAdmin(admin.ModelAdmin):
    list_display = ['id', 'booking', 'from_bed', 'to_bed', 'action', 'actor', 'created_at']
    list_filter = ['action', 'created_at']


@admin.register(HostelMutualSwitchRequest)
class HostelMutualSwitchRequestAdmin(admin.ModelAdmin):
    list_display = ['id', 'requester', 'partner', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['requester_booking__student__username', 'partner_booking__student__username']

    def requester(self, obj):
        return f"{obj.requester_booking.student.username} ({obj.requester_booking.bed})"

    def partner(self, obj):
        if obj.partner_booking:
            return f"{obj.partner_booking.student.username} ({obj.partner_booking.bed})"
        return "OPEN"


@admin.register(HostelMutualSwitchHistory)
class HostelMutualSwitchHistoryAdmin(admin.ModelAdmin):
    list_display = ['id', 'booking_a', 'booking_b', 'from_bed_a', 'to_bed_a', 'from_bed_b', 'to_bed_b', 'action',
                    'actor', 'created_at']
    list_filter = ['action', 'created_at']
