from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import HostelRoomViewSet, HostelBedViewSet, HostelBookingViewSet, HostelMonthlyFeeViewSet, \
    generate_hostel_invoice, hostel_billing_summary, student_hostel_booking_status, download_hostel_invoice_pdf, \
    MyHostelInvoicesView, AdminHostelInvoiceViewSet, mark_hostel_invoice_paid, generate_hostel_invoices_bulk, \
    HostelAvailableSwitchRequestViewSet, HostelMutualSwitchRequestViewSet, HostelAvailableSwitchHistoryViewSet, \
    HostelMutualSwitchHistoryViewSet

router = DefaultRouter()
router.register('rooms', HostelRoomViewSet)
router.register('beds', HostelBedViewSet)
router.register('bookings', HostelBookingViewSet)
router.register('monthly-fee', HostelMonthlyFeeViewSet)
router.register(r'hostel/bookings', HostelBookingViewSet, basename='hostel-bookings-alt')
router.register('admin/hostel-invoices', AdminHostelInvoiceViewSet, basename='admin-hostel-invoices')

router.register('switch-requests/available', HostelAvailableSwitchRequestViewSet, basename='hostel-available-switch')
router.register('switch-requests/mutual', HostelMutualSwitchRequestViewSet, basename='hostel-mutual-switch')

router.register('switch-history/available', HostelAvailableSwitchHistoryViewSet,
                basename='hostel-available-switch-history')
router.register('switch-history/mutual', HostelMutualSwitchHistoryViewSet, basename='hostel-mutual-switch-history')

urlpatterns = [
    path('', include(router.urls)),
    path('admin/hostel-dashboard-stats/', HostelBookingViewSet.hostel_dashboard_stats),
    path('admin/export-csv/', HostelBookingViewSet.export_hostel_bookings_csv),
    path('bookings/<int:pk>/cancel/', HostelBookingViewSet.as_view({'post': 'cancel'})),
    path('generate-next-month-invoice/', generate_hostel_invoice),
    path('billing-summary/', hostel_billing_summary, name='hostel-billing-summary'),
    path('booking-status/', student_hostel_booking_status),
    path('invoices/<int:invoice_id>/download-pdf/', download_hostel_invoice_pdf, name='download_hostel_invoice_pdf'),
    path('my-invoices/', MyHostelInvoicesView.as_view(), name='my_hostel_invoices'),
    path('invoices/<int:invoice_id>/mark-paid/', mark_hostel_invoice_paid, name='mark_hostel_invoice_paid'),
    path('admin/generate-central-invoices/', generate_hostel_invoices_bulk),

]
