from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle
from io import BytesIO
import os
from django.conf import settings

def generate_student_profile_pdf(student, hostel_bookings, library_bookings, complaints, reviews):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50

    def draw_line(text, font="Helvetica", size=12, x=50, dy=20):
        nonlocal y
        p.setFont(font, size)
        p.drawString(x, y, text)
        y -= dy

    # 🏠 Heading
    draw_line("Bussiness Track Hostel & Library", font="Helvetica-Bold", size=16, dy=30)
    draw_line("Student Profile Report", font="Helvetica-Bold", size=14, dy=25)

    # 👤 Profile Photo and Aadhaar Images
    profile_photo = student.profile_photo.path if student.profile_photo and os.path.exists(student.profile_photo.path) else None
    aadhaar_front = None
    aadhaar_back = None

    latest_hostel = hostel_bookings.last()
    latest_library = library_bookings.last()

    if latest_hostel:
        aadhaar_front = latest_hostel.aadhaar_front_photo.path if latest_hostel.aadhaar_front_photo else None
        aadhaar_back = latest_hostel.aadhaar_back_photo.path if latest_hostel.aadhaar_back_photo else None
    if not aadhaar_front and latest_library:
        aadhaar_front = latest_library.aadhaar_front_photo.path if latest_library.aadhaar_front_photo else None
    if not aadhaar_back and latest_library:
        aadhaar_back = latest_library.aadhaar_back_photo.path if latest_library.aadhaar_back_photo else None

    # 📷 Draw Images
    image_y = y
    if profile_photo and os.path.exists(profile_photo):
        p.drawImage(profile_photo, 400, image_y - 20, width=80, height=80, preserveAspectRatio=True)
    if aadhaar_front and os.path.exists(aadhaar_front):
        p.drawImage(aadhaar_front, 50, image_y - 100, width=80, height=50, preserveAspectRatio=True)
    if aadhaar_back and os.path.exists(aadhaar_back):
        p.drawImage(aadhaar_back, 150, image_y - 100, width=80, height=50, preserveAspectRatio=True)

    y -= 120

    # 👤 Student Details
    draw_line(f"Name: {student.get_full_name()}")
    draw_line(f"Username: {student.username}")
    draw_line(f"Email: {student.email}")
    draw_line(f"Phone: {student.phone_number}")
    draw_line(f"Address: {student.address}")
    draw_line(f"Education: {student.education}")
    y -= 20

    def draw_table(title, data, colWidths=None):
        nonlocal y
        draw_line(title, font="Helvetica-Bold", size=13, dy=25)
        table = Table(data, colWidths=colWidths)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 0.25, colors.black),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ]))
        table.wrapOn(p, width, height)
        table_height = len(data) * 15
        if y - table_height < 100:
            p.showPage()
            y = height - 50
        table.drawOn(p, 50, y - table_height)
        y -= table_height + 30

    # 🛏 Hostel Bookings
    hostel_data = [["Room", "Bed", "Start Date", "Status"]]
    for b in hostel_bookings:
        hostel_data.append([
            b.bed.room.room_number if b.bed and b.bed.room else '',
            b.bed.bed_number if b.bed else '',
            str(b.start_date),
            b.status.upper()
        ])
    if len(hostel_data) > 1:
        draw_table("Hostel Booking History", hostel_data, [80, 80, 100, 100])

    # 🪑 Library Bookings
    library_data = [["Seat", "Start Date", "Status"]]
    for b in library_bookings:
        library_data.append([
            b.seat.seat_number if b.seat else '',
            str(b.start_date),
            b.status.upper()
        ])
    if len(library_data) > 1:
        draw_table("Library Booking History", library_data, [100, 100, 100])

    # 🗳 Complaints
    complaint_data = [["Title", "Category", "Status", "Submitted On"]]
    for c in complaints:
        complaint_data.append([
            c.title, c.category, c.status, c.submitted_on.strftime('%d-%b-%Y')
        ])
    if len(complaint_data) > 1:
        draw_table("Complaints", complaint_data)

    # 💬 Reviews
    review_data = [["Title", "Rating", "Submitted On"]]
    for r in reviews:
        review_data.append([
            r.title or '', f"⭐ {r.rating}", r.submitted_on.strftime('%d-%b-%Y')
        ])
    if len(review_data) > 1:
        draw_table("Reviews", review_data)

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer
