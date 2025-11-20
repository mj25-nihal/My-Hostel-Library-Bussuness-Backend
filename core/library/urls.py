from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import LibrarySeatViewSet, TimeSlotViewSet, LibraryBookingViewSet, LibraryMonthlyFeeViewSet, \
    generate_library_invoice, library_billing_summary, student_library_booking_status, download_library_invoice_pdf, \
    MyLibraryInvoicesView, AdminLibraryInvoiceViewSet, mark_library_invoice_paid, generate_library_invoices_bulk, \
    LibraryAvailableSwitchRequestViewSet, LibraryMutualSwitchRequestViewSet, LibraryAvailableSwitchHistoryViewSet, \
    LibraryMutualSwitchHistoryViewSet

router = DefaultRouter()
router.register('seats', LibrarySeatViewSet)
router.register('timeslots', TimeSlotViewSet)
router.register('bookings', LibraryBookingViewSet)
router.register('monthly-fee', LibraryMonthlyFeeViewSet)
router.register(r'library/bookings', LibraryBookingViewSet, basename='library-bookings-alt')
router.register('admin/library-invoices', AdminLibraryInvoiceViewSet, basename='admin-library-invoices')

router.register('switch-requests/available', LibraryAvailableSwitchRequestViewSet, basename='library-available-switch')
router.register('switch-requests/mutual', LibraryMutualSwitchRequestViewSet, basename='library-mutual-switch')

router.register('switch-history/available', LibraryAvailableSwitchHistoryViewSet, basename='library-available-switch-history')
router.register('switch-history/mutual', LibraryMutualSwitchHistoryViewSet, basename='library-mutual-switch-history')

urlpatterns = [
    path('', include(router.urls)),
    path('admin/library-dashboard-stats/', LibraryBookingViewSet.library_dashboard_stats),
    path('admin/export-csv/', LibraryBookingViewSet.export_library_bookings_csv),
    path('bookings/<int:pk>/cancel/', LibraryBookingViewSet.as_view({'post': 'cancel'})),
    path('generate-next-month-invoice/', generate_library_invoice),
    path('billing-summary/', library_billing_summary, name='library-billing-summary'),
    path('booking-status/', student_library_booking_status),
    path('invoices/<int:invoice_id>/download-pdf/', download_library_invoice_pdf, name='download_library_invoice_pdf'),
    path('my-invoices/', MyLibraryInvoicesView.as_view(), name='my_library_invoices'),
    path('invoices/<int:invoice_id>/mark-paid/', mark_library_invoice_paid, name='mark_library_invoice_paid'),
    path('admin/generate-central-invoices/', generate_library_invoices_bulk),

]
