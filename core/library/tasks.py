from celery import shared_task
from datetime import date, timedelta
from library.models import LibraryMonthlyInvoice

@shared_task
def reset_library_invoice_payments():
    today = date.today()
    invoices = LibraryMonthlyInvoice.objects.filter(is_paid=True)

    count = 0
    for invoice in invoices:
        if today > (invoice.month + timedelta(days=30)):
            invoice.is_paid = False
            invoice.save()
            count += 1

    return f"{count} library invoices reset to unpaid."
