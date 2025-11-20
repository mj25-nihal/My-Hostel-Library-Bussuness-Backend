from django.db import models
from django.conf import settings
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from django.db.models.signals import post_save
from django.dispatch import receiver
from datetime import date, timedelta
from django.db import transaction


class HostelRoom(models.Model):
    room_number = models.CharField(max_length=50, unique=True)
    capacity = models.PositiveIntegerField()

    def __str__(self):
        return f"Room {self.room_number}"


class HostelBed(models.Model):
    room = models.ForeignKey(HostelRoom, on_delete=models.CASCADE, related_name='beds')
    bed_number = models.CharField(max_length=50)
    description = models.TextField(blank=True, null=True)
    is_booked = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.room.room_number} - Bed {self.bed_number}"


class HostelBooking(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    )

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name='hostel_bookings_as_student')
    bed = models.ForeignKey('HostelBed', on_delete=models.CASCADE, related_name='bookings', null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True, default=None)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='hostel_bookings_as_approver')
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    remarks = models.TextField(null=True, blank=True)
    aadhaar_front_photo = models.ImageField(upload_to='profile_photos/')
    aadhaar_back_photo = models.ImageField(upload_to='profile_photos/')
    purpose_of_joining = models.TextField(default="", help_text="For which study you want to join the hostel?")
    # student_photo = models.ImageField(upload_to='student_photos/')
    monthly_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    deposit_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.student.username} - Bed {self.bed.id} - {self.status}"

    def save(self, *args, **kwargs):
        # Auto mark bed as booked/unbooked
        if self.status == 'approved':
            self.bed.is_booked = True
            self.bed.save()
        elif self.status in ['rejected', 'cancelled', 'expired']:
            # Check if there are any other approved bookings for this bed
            if not HostelBooking.objects.filter(bed=self.bed, status='approved').exclude(id=self.id).exists():
                self.bed.is_booked = False
                self.bed.save()

        super().save(*args, **kwargs)  # Save the booking

        # OPTIONAL: Debug/log to confirm
        print(f" Booking status updated: {self.status}, Bed {self.bed.bed_number} → is_booked={self.bed.is_booked}")

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

        # Calculate number of calendar months
        rdelta = relativedelta(as_of, self.start_date)
        months = rdelta.years * 12 + rdelta.months + (1 if rdelta.days >= 0 else 0)

        total = (self.monthly_fee * months) + self.deposit_amount
        return total


class HostelMonthlyFee(models.Model):
    monthly_fee = models.DecimalField(max_digits=10, decimal_places=2, default=1500.00)
    deposit_amount = models.DecimalField(max_digits=10, decimal_places=2, default=2000.00)
    effective_from = models.DateField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Hostel Fee ₹{self.monthly_fee}/mo, Deposit ₹{self.deposit_amount}"


# hostel/models.py

class HostelFeeSetting(models.Model):
    monthly_fee = models.DecimalField(max_digits=8, decimal_places=2, default=1500.00)
    deposit = models.DecimalField(max_digits=8, decimal_places=2, default=2000.00)

    def __str__(self):
        return f"Hostel Fee: ₹{self.monthly_fee}, Deposit: ₹{self.deposit}"


from .models import HostelBooking


class HostelMonthlyInvoice(models.Model):
    booking = models.ForeignKey(HostelBooking, on_delete=models.CASCADE, related_name='invoices')
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


# ========= SWITCH REQUESTS (HOSTEL) =========


class HostelAvailableSwitchRequest(models.Model):
    STATUS = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    )
    booking = models.ForeignKey('HostelBooking', on_delete=models.CASCADE, related_name='available_switch_requests')
    target_bed = models.ForeignKey('HostelBed', on_delete=models.CASCADE, related_name='incoming_switch_requests')
    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    remarks = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='hostel_available_switch_approver')

    def __str__(self):
        return f"AvailSwitch #{self.id} – {self.booking.student.username} -> Bed {self.target_bed_id}"


class HostelAvailableSwitchHistory(models.Model):
    ACTIONS = (('approved', 'Approved'), ('rejected', 'Rejected'), ('cancelled', 'Cancelled'),)
    booking = models.ForeignKey('HostelBooking', on_delete=models.CASCADE, related_name='available_switch_history')
    from_bed = models.ForeignKey('HostelBed', on_delete=models.SET_NULL, null=True, related_name='+')
    to_bed = models.ForeignKey('HostelBed', on_delete=models.SET_NULL, null=True, related_name='+')
    action = models.CharField(max_length=20, choices=ACTIONS)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    remarks = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class HostelMutualSwitchRequest(models.Model):
    STATUS = (
        ('pending', 'Pending'),          # waiting for match/approval
        ('approved', 'Approved'),        # swap done
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    )
    requester_booking = models.ForeignKey('HostelBooking', on_delete=models.CASCADE, related_name='mutual_requests')
    partner_booking = models.ForeignKey('HostelBooking', on_delete=models.CASCADE, null=True, blank=True,
                                        related_name='incoming_mutual_requests')  # NULL => OPEN mutual
    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    remarks = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(blank=True, null=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='hostel_mutual_switch_approver')

    def __str__(self):
        tgt = self.partner_booking_id or "OPEN"
        return f"MutualSwitch #{self.id} – {self.requester_booking.student.username} ↔ {tgt}"


class HostelMutualSwitchHistory(models.Model):
    ACTIONS = (('approved', 'Approved'), ('rejected', 'Rejected'), ('cancelled', 'Cancelled'),)
    booking_a = models.ForeignKey('HostelBooking', on_delete=models.SET_NULL, null=True, related_name='+')
    booking_b = models.ForeignKey('HostelBooking', on_delete=models.SET_NULL, null=True, related_name='+')
    from_bed_a = models.ForeignKey('HostelBed', on_delete=models.SET_NULL, null=True, related_name='+')
    to_bed_a = models.ForeignKey('HostelBed', on_delete=models.SET_NULL, null=True, related_name='+')
    from_bed_b = models.ForeignKey('HostelBed', on_delete=models.SET_NULL, null=True, related_name='+')
    to_bed_b = models.ForeignKey('HostelBed', on_delete=models.SET_NULL, null=True, related_name='+')
    action = models.CharField(max_length=20, choices=ACTIONS)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    remarks = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
