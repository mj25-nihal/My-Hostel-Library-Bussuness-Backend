from django.db.models import Sum
from hostel.models import HostelMonthlyInvoice
from library.models import LibraryMonthlyInvoice

class HostelRevenueService:
    @staticmethod
    def get_summary(start_date=None, end_date=None):
        qs = HostelMonthlyInvoice.objects.all()
        if start_date and end_date:
            qs = qs.filter(generated_on__range=[start_date, end_date])
        return {
            "total_paid": qs.filter(is_paid=True).aggregate(Sum('total'))['total__sum'] or 0,
            "total_pending": qs.filter(is_paid=False).aggregate(Sum('total'))['total__sum'] or 0,
            "count_paid": qs.filter(is_paid=True).count(),
            "count_pending": qs.filter(is_paid=False).count(),
        }

class LibraryRevenueService:
    @staticmethod
    def get_summary(start_date=None, end_date=None):
        qs = LibraryMonthlyInvoice.objects.all()
        if start_date and end_date:
            qs = qs.filter(generated_on__range=[start_date, end_date])
        return {
            "total_paid": qs.filter(is_paid=True).aggregate(Sum('total'))['total__sum'] or 0,
            "total_pending": qs.filter(is_paid=False).aggregate(Sum('total'))['total__sum'] or 0,
            "count_paid": qs.filter(is_paid=True).count(),
            "count_pending": qs.filter(is_paid=False).count(),
        }

class CombinedRevenueService:
    @staticmethod
    def get_summary(start_date=None, end_date=None):
        hostel = HostelRevenueService.get_summary(start_date, end_date)
        library = LibraryRevenueService.get_summary(start_date, end_date)

        return {
            "hostel": hostel,
            "library": library,
            "combined": {
                "total_paid": hostel['total_paid'] + library['total_paid'],
                "total_pending": hostel['total_pending'] + library['total_pending'],
                "count_paid": hostel['count_paid'] + library['count_paid'],
                "count_pending": hostel['count_pending'] + library['count_pending'],
            }
        }
