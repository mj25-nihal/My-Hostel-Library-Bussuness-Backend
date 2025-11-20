# hostel/tasks.py

from celery import shared_task
from datetime import date, timedelta
from hostel.models import HostelMonthlyInvoice


@shared_task
def reset_hostel_invoice_payments():
    today = date.today()
    invoices = HostelMonthlyInvoice.objects.filter(is_paid=True)

    count = 0
    for invoice in invoices:
        if today > (invoice.month + timedelta(days=30)):
            invoice.is_paid = False
            invoice.save()
            count += 1

    return f"{count} hostel invoices reset to unpaid."

# from django.utils import timezone
# from hostel.models import HostelBooking
# from library.models import LibraryBooking
# from core.utils.sms_utils import send_sms
# from core.utils.email_utils import send_rejection_email
# from channels.layers import get_channel_layer
# from asgiref.sync import async_to_sync
#
# @shared_task
# def release_expired_bookings_task():
#     today = timezone.now().date()
#     hostel_count, library_count = 0, 0
#
#     expired_hostel = HostelBooking.objects.filter(end_date__lt=today, status='approved')
#     for booking in expired_hostel:
#         booking.status = 'expired'
#         booking.bed.is_booked = False
#         booking.bed.save()
#         booking.save()
#         hostel_count += 1
#
#         send_rejection_email(booking.student.email, booking.student.username, "Hostel")
#         if booking.student.phone_number:
#             try:
#                 send_sms(
#                     booking.student.phone_number,
#                     f"Hi {booking.student.username}, your hostel booking has expired and bed is released."
#                 )
#             except Exception as e:
#                 print("SMS failed:", e)
#
#         channel_layer = get_channel_layer()
#         async_to_sync(channel_layer.group_send)(
#             "live_seat_updates",
#             {
#                 "type": "send_seat_update",
#                 "data": {
#                     "type": "booking_expired",
#                     "bed_id": booking.bed.id,
#                     "is_booked": False,
#                 }
#             }
#         )
#
#     expired_library = LibraryBooking.objects.filter(end_date__lt=today, status='approved')
#     for booking in expired_library:
#         booking.status = 'expired'
#         booking.seat.is_booked = False
#         booking.seat.save()
#         booking.save()
#         library_count += 1
#
#         send_rejection_email(booking.student.email, booking.student.username, "Library")
#         if booking.student.phone_number:
#             try:
#                 send_sms(
#                     booking.student.phone_number,
#                     f"Hi {booking.student.username}, your library booking has expired and seat is released."
#                 )
#             except Exception as e:
#                 print("SMS failed:", e)
#
#         async_to_sync(channel_layer.group_send)(
#             "live_seat_updates",
#             {
#                 "type": "send_seat_update",
#                 "data": {
#                     "type": "library_booking_expired",
#                     "seat_id": booking.seat.id,
#                     "is_booked": False,
#                 }
#             }
#         )
#
#     return f"{hostel_count} hostel & {library_count} library bookings expired and released."
