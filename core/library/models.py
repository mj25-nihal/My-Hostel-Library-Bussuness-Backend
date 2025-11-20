from django.db import models
from django.conf import settings
from dateutil.relativedelta import relativedelta
from datetime import date, timedelta
from django.db import transaction

class LibrarySeat(models.Model):
    seat_number = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, null=True)
    is_booked = models.BooleanField(default=False)

    def __str__(self):
        return f"Seat {self.seat_number}"


class TimeSlot(models.Model):
    start_time = models.TimeField()
    end_time = models.TimeField()

    def __str__(self):
        return f"{self.start_time} - {self.end_time}"


class LibraryBooking(models.Model):
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    seat = models.ForeignKey(LibrarySeat, on_delete=models.CASCADE)

    # Start date only (no end date)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True, default=None)
    # Photo uploads
    aadhaar_front_photo = models.ImageField(upload_to='profile_photos/')
    aadhaar_back_photo = models.ImageField(upload_to='profile_photos/')
    purpose_of_joining = models.TextField(default="", help_text="For which study you want to join the study centre ?")
    # student_photo = models.ImageField(upload_to='student_photos/')

    # Updated statuses including 'cancelled'
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('expired', 'Expired'),
            ('cancelled', 'Cancelled'),
        ],
        default='pending'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    remarks = models.TextField(null=True, blank=True)
    monthly_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    deposit_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.student.username} - {self.seat} from {self.start_date}"

    def save(self, *args, **kwargs):
        # Automatically update seat booking status
        if self.status == 'approved':
            self.seat.is_booked = True
            self.seat.save()
        elif self.status in ['rejected', 'cancelled', 'expired']:
            # Check if other approved bookings exist
            if not LibraryBooking.objects.filter(seat=self.seat, status='approved').exclude(id=self.id).exists():
                self.seat.is_booked = False
                self.seat.save()

        super().save(*args, **kwargs)  # Save the booking itself

        # Optional debug log
        print(f" Library booking updated: seat={self.seat.id}, status={self.status}, is_booked={self.seat.is_booked}")

    def calculate_total_due(self, as_of_date=None):
        """
        Calculates total due till current date (or passed date):
        monthly_fee × months active + deposit (only once)
        """
        if self.status != 'approved':
            return 0

        if not self.start_date or not self.monthly_fee:
            return 0

        from datetime import date
        as_of = as_of_date or date.today()

        rdelta = relativedelta(as_of, self.start_date)
        months = rdelta.years * 12 + rdelta.months + (1 if rdelta.days >= 0 else 0)

        total = (self.monthly_fee * months) + self.deposit_amount
        return total


from django.db import models
from django.utils import timezone


class LibraryMonthlyFee(models.Model):
    monthly_fee = models.DecimalField(max_digits=10, decimal_places=2, default=600.00)
    deposit_amount = models.DecimalField(max_digits=10, decimal_places=2, default=500.00)
    effective_from = models.DateField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Library Fee ₹{self.monthly_fee}/mo, Deposit ₹{self.deposit_amount}"


# library/models.py

class LibraryFeeSetting(models.Model):
    monthly_fee = models.DecimalField(max_digits=8, decimal_places=2, default=600.00)
    deposit = models.DecimalField(max_digits=8, decimal_places=2, default=500.00)

    def __str__(self):
        return f"Library Fee: ₹{self.monthly_fee}, Deposit: ₹{self.deposit}"


from .models import LibraryBooking


class LibraryMonthlyInvoice(models.Model):
    booking = models.ForeignKey(LibraryBooking, on_delete=models.CASCADE, related_name='invoices')
    invoice_id = models.CharField(max_length=30, unique=True)
    month = models.DateField()
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    deposit = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=8, decimal_places=2)
    is_paid = models.BooleanField(default=False)
    generated_on = models.DateTimeField(auto_now_add=True)
    invoice_expired = models.BooleanField(default=False)

    class Meta:
        unique_together = ['booking', 'month']

    def __str__(self):
        return f"{self.invoice_id} – {self.booking.student.username}"



# ========= SWITCH REQUESTS (LIBRARY) =========


class LibraryAvailableSwitchRequest(models.Model):
    STATUS = (('pending','Pending'),('approved','Approved'),('rejected','Rejected'),('cancelled','Cancelled'))
    booking = models.ForeignKey('LibraryBooking', on_delete=models.CASCADE, related_name='available_switch_requests')
    target_seat = models.ForeignKey('LibrarySeat', on_delete=models.CASCADE, related_name='incoming_switch_requests')
    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    remarks = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='library_available_switch_approver')

    def __str__(self):
        return f"AvailSwitch #{self.id} – {self.booking.student.username} -> Seat {self.target_seat_id}"


class LibraryAvailableSwitchHistory(models.Model):
    ACTIONS = (('approved','Approved'),('rejected','Rejected'),('cancelled','Cancelled'))
    booking = models.ForeignKey('LibraryBooking', on_delete=models.CASCADE, related_name='available_switch_history')
    from_seat = models.ForeignKey('LibrarySeat', on_delete=models.SET_NULL, null=True, related_name='+')
    to_seat = models.ForeignKey('LibrarySeat', on_delete=models.SET_NULL, null=True, related_name='+')
    action = models.CharField(max_length=20, choices=ACTIONS)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    remarks = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class LibraryMutualSwitchRequest(models.Model):
    STATUS = (('pending','Pending'),('approved','Approved'),('rejected','Rejected'),('cancelled','Cancelled'))
    requester_booking = models.ForeignKey('LibraryBooking', on_delete=models.CASCADE, related_name='mutual_requests')
    partner_booking = models.ForeignKey('LibraryBooking', on_delete=models.CASCADE, null=True, blank=True,
                                        related_name='incoming_mutual_requests')  # NULL => OPEN mutual
    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    remarks = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='library_mutual_switch_approver')

    def __str__(self):
        tgt = self.partner_booking_id or "OPEN"
        return f"MutualSwitch #{self.id} – {self.requester_booking.student.username} ↔ {tgt}"


class LibraryMutualSwitchHistory(models.Model):
    ACTIONS = (('approved','Approved'),('rejected','Rejected'),('cancelled','Cancelled'))
    booking_a = models.ForeignKey('LibraryBooking', on_delete=models.SET_NULL, null=True, related_name='+')
    booking_b = models.ForeignKey('LibraryBooking', on_delete=models.SET_NULL, null=True, related_name='+')
    from_seat_a = models.ForeignKey('LibrarySeat', on_delete=models.SET_NULL, null=True, related_name='+')
    to_seat_a = models.ForeignKey('LibrarySeat', on_delete=models.SET_NULL, null=True, related_name='+')
    from_seat_b = models.ForeignKey('LibrarySeat', on_delete=models.SET_NULL, null=True, related_name='+')
    to_seat_b = models.ForeignKey('LibrarySeat', on_delete=models.SET_NULL, null=True, related_name='+')
    action = models.CharField(max_length=20, choices=ACTIONS)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    remarks = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
