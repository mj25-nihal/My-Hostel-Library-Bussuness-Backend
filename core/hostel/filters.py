import django_filters
from .models import HostelMonthlyInvoice

class HostelInvoiceFilter(django_filters.FilterSet):
    month = django_filters.CharFilter(method='filter_month')
    year = django_filters.NumberFilter(field_name='month', lookup_expr='year')
    is_paid = django_filters.BooleanFilter()

    class Meta:
        model = HostelMonthlyInvoice
        fields = ['month', 'year', 'is_paid']

    def filter_month(self, queryset, name, value):
        try:
            year, month = value.split('-')
            return queryset.filter(month__year=year, month__month=month)
        except:
            return queryset.none()
