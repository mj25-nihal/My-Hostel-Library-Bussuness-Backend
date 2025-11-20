from django.core.management.base import BaseCommand
from django.utils import timezone
from hostel.models import HostelBooking
from library.models import LibraryBooking

class Command(BaseCommand):
    help = 'Auto-release expired hostel and library bookings'

    def handle(self, *args, **kwargs):
        today = timezone.now().date()

        # Hostel logic
        expired_hostel = HostelBooking.objects.filter(end_date__lt=today, status='approved')
        hostel_count = 0
        for booking in expired_hostel:
            booking.status = 'expired'
            booking.bed.is_booked = False
            booking.bed.save()
            booking.save()
            hostel_count += 1

        # Library logic
        expired_library = LibraryBooking.objects.filter(booking_date__lt=today, status='approved')
        library_count = 0
        for booking in expired_library:
            booking.status = 'expired'
            booking.seat.is_booked = False
            booking.seat.save()
            booking.save()
            library_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'{hostel_count} hostel bookings & {library_count} library bookings auto-released. ✅'
        ))
