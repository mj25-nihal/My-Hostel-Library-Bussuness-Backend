from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from datetime import date
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.colors import red, green
import os

#  Watermark function
def add_watermark(canvas, doc, text, color):
    canvas.saveState()
    canvas.setFont("Helvetica-Bold", 100)  # Big font
    canvas.setFillColorRGB(*color, alpha=0.40)  # Light transparency feel

    width, height = A4
    canvas.translate(width / 2, height / 2)
    canvas.rotate(45)
    canvas.drawCentredString(0, 0, text)
    canvas.restoreState()


#  Hostel invoice with PAID/UNPAID watermark
def generate_hostel_invoice_pdf(invoice):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("<b>Bussiness Track Hostel & Library</b>", styles['Title']))
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(f"Invoice ID: {invoice.invoice_id}", styles['Normal']))
    elements.append(Paragraph(f"Month: {invoice.month.strftime('%d-%b-%Y')}", styles['Normal']))
    elements.append(Spacer(1, 10))

    student = invoice.booking.student
    bed = invoice.booking.bed

    elements.append(Paragraph(f"Student: {student.first_name} {student.last_name}", styles['Normal']))
    elements.append(Paragraph(f"Phone: {student.phone_number}", styles['Normal']))
    elements.append(Paragraph(f"Room: {bed.room.room_number if bed else '-'} | Bed: {bed.bed_number if bed else '-'}", styles['Normal']))
    elements.append(Spacer(1, 20))

    data = [
        ['Description', 'Amount (₹)'],
        ['Monthly Fee', f"{invoice.amount}"],
        ['Deposit', f"{invoice.deposit}"],
        ['Total', f"{invoice.total}"]
    ]

    table = Table(data, colWidths=[300, 200])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 30))
    elements.append(Paragraph("Thank you for your payment!", styles['Italic']))

    #  Watermark logic
    status_text = "PAID" if invoice.is_paid else "UNPAID"
    status_color = (0, 1, 0) if invoice.is_paid else (1, 0, 0)  # Green or Red RGB
    doc.build(
        elements,
        onFirstPage=lambda c, d: add_watermark(c, d, status_text, status_color)
    )

    buffer.seek(0)
    return buffer

#  Library invoice with watermark
def generate_library_invoice_pdf(invoice):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("<b>Bussiness Track Hostel & Library</b>", styles['Title']))
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(f"Invoice ID: {invoice.invoice_id}", styles['Normal']))
    elements.append(Paragraph(f"Month: {invoice.month.strftime('%d-%b-%Y')}", styles['Normal']))
    elements.append(Spacer(1, 10))

    student = invoice.booking.student
    seat = invoice.booking.seat

    elements.append(Paragraph(f"Student: {student.first_name} {student.last_name}", styles['Normal']))
    elements.append(Paragraph(f"Phone: {student.phone_number}", styles['Normal']))
    elements.append(Paragraph(f"Seat: {seat.seat_number if seat else '-'}", styles['Normal']))
    elements.append(Spacer(1, 20))

    data = [
        ['Description', 'Amount (₹)'],
        ['Monthly Fee', f"{invoice.amount}"],
        ['Deposit', f"{invoice.deposit}"],
        ['Total', f"{invoice.total}"]
    ]

    table = Table(data, colWidths=[300, 200])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 30))
    elements.append(Paragraph("Thank you for your payment!", styles['Italic']))

    #  Watermark logic
    status_text = "PAID" if invoice.is_paid else "UNPAID"
    status_color = (0, 1, 0) if invoice.is_paid else (1, 0, 0)  # Green or Red RGB
    doc.build(
        elements,
        onFirstPage=lambda c, d: add_watermark(c, d, status_text, status_color)
    )

    buffer.seek(0)
    return buffer








# Booking invoice for booking screen (not monthly invoice)
def generate_invoice_pdf(booking, student_name, total_due, months, monthly_fee, deposit):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    p.setFont("Helvetica-Bold", 18)
    p.drawString(200, height - 50, "Booking Invoice")

    p.setFont("Helvetica", 12)
    p.drawString(50, height - 100, f"Name: {student_name}")
    p.drawString(50, height - 120, f"Start Date: {booking.start_date}")
    p.drawString(50, height - 140, f"Status: {booking.status.upper()}")
    p.drawString(50, height - 160, f"Monthly Fee: ₹{monthly_fee}")
    p.drawString(50, height - 180, f"Months Active: {months}")
    p.drawString(50, height - 200, f"Deposit: ₹{deposit}")
    p.drawString(50, height - 230, f"Total Amount Due: ₹{total_due}")

    p.drawString(50, height - 270, "Thank you for using our Hostel & Library system.")
    p.showPage()
    p.save()

    buffer.seek(0)
    return buffer


# Invoice ID generator
def generate_invoice_id(prefix: str, booking_id: int, month: date):
    """
    Example: INV-HO-202506-001
    """
    return f"INV-{prefix.upper()}-{month.strftime('%Y%m')}-{booking_id:03d}"

