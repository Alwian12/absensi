from __future__ import annotations

from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.authentication.jwt_handler import verify_token
from app.database import SessionLocal
from app.models.assessment import Assessment
from app.models.attendance import Attendance
from app.models.journal import Journal
from app.models.participant import Participant
from app.models.user import User

router = APIRouter(prefix="/api/reports", tags=["reports"])


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_request_user(request: Request, db: Session, authorization: str | None = Header(default=None)) -> User:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        try:
            payload = verify_token(token)
            user_id = int(payload["sub"])
            user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
            if user:
                return user
        except Exception:
            pass

    raw_user_id = request.cookies.get("user_id")
    if raw_user_id and raw_user_id.isdigit():
        user = db.query(User).filter(User.id == int(raw_user_id), User.is_active == True).first()
        if user:
            return user

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def ensure_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")


def apply_attendance_review_filter(query, review_filter: str):
    key = (review_filter or "all").strip().lower()
    if key == "pending":
        return query.filter(Attendance.location_review_status == "pending")
    if key == "approved":
        return query.filter(Attendance.location_review_status == "approved")
    if key == "rejected":
        return query.filter(Attendance.location_review_status == "rejected")
    if key == "grace":
        return query.filter(Attendance.location_review_reason.in_(["grace", "grace_and_risk"]))
    if key == "risk":
        return query.filter(Attendance.location_review_reason.in_(["risk", "grace_and_risk"]))
    if key == "needs_review":
        return query.filter(Attendance.requires_location_review == True)
    return query


def attendance_dataset(db: Session, review_filter: str = "all") -> list[dict[str, object]]:
    query = db.query(Attendance)
    query = apply_attendance_review_filter(query, review_filter)
    rows = query.order_by(Attendance.id.asc()).all()
    return [
        {
            "id": row.id,
            "user_id": row.user_id,
            "status": row.status,
            "check_in_time": row.check_in_time.isoformat() if row.check_in_time else "",
            "check_out_time": row.check_out_time.isoformat() if row.check_out_time else "",
            "confidence_score": row.confidence_score if row.confidence_score is not None else "",
            "location_review_status": row.location_review_status or "not_required",
            "location_review_reason": row.location_review_reason or "",
            "requires_location_review": bool(row.requires_location_review),
            "location_review_note": row.location_review_note or "",
        }
        for row in rows
    ]


@router.get("/attendance/excel")
def export_attendance_excel(
    request: Request,
    review_filter: str = Query(default="all"),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> StreamingResponse:
    try:
        import pandas as pd
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="Pandas belum terpasang di environment server") from exc

    user = get_request_user(request, db, authorization)
    ensure_admin(user)

    data = attendance_dataset(db, review_filter)
    df = pd.DataFrame(data)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="attendance")

    output.seek(0)
    filename = f"attendance-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/attendance/pdf")
def export_attendance_pdf(
    request: Request,
    review_filter: str = Query(default="all"),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> StreamingResponse:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="ReportLab belum terpasang di environment server") from exc

    user = get_request_user(request, db, authorization)
    ensure_admin(user)

    data = attendance_dataset(db, review_filter)

    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    width, height = A4

    pdf.setTitle("Attendance Report")
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(40, height - 40, "Attendance Report")
    pdf.setFont("Helvetica", 9)
    pdf.drawString(40, height - 55, f"Generated at: {datetime.now().isoformat(timespec='seconds')}")

    y = height - 80
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(40, y, "ID")
    pdf.drawString(80, y, "User")
    pdf.drawString(130, y, "Status")
    pdf.drawString(200, y, "Check In")
    pdf.drawString(340, y, "Check Out")
    pdf.drawString(450, y, "Confidence")
    pdf.drawString(510, y, "Review")

    pdf.setFont("Helvetica", 8)
    y -= 16
    for item in data:
        if y < 50:
            pdf.showPage()
            y = height - 40
            pdf.setFont("Helvetica", 8)
        pdf.drawString(40, y, str(item["id"]))
        pdf.drawString(80, y, str(item["user_id"]))
        pdf.drawString(130, y, str(item["status"]))
        pdf.drawString(200, y, str(item["check_in_time"])[:19])
        pdf.drawString(340, y, str(item["check_out_time"])[:19])
        pdf.drawString(450, y, str(item["confidence_score"]))
        review_cell = str(item.get("location_review_status", ""))
        reason_cell = str(item.get("location_review_reason", ""))
        if reason_cell:
            review_cell = f"{review_cell}:{reason_cell}"
        pdf.drawString(510, y, review_cell[:18])
        y -= 14

    pdf.save()
    output.seek(0)

    filename = f"attendance-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.pdf"
    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/peserta/{user_id}/pdf")
def export_peserta_pdf(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> StreamingResponse:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    requester = get_request_user(request, db, authorization)
    if requester.role not in {"admin", "pembimbing"} and requester.id != user_id:
        raise HTTPException(status_code=403, detail="Akses ditolak")

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan")

    participant = db.query(Participant).filter(Participant.user_id == user_id).first()
    attendances = db.query(Attendance).filter(Attendance.user_id == user_id).order_by(Attendance.id.asc()).all()
    journals = db.query(Journal).filter(Journal.user_id == user_id).order_by(Journal.id.asc()).all()
    assessments = db.query(Assessment).filter(Assessment.user_id == user_id).order_by(Assessment.id.asc()).all()

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    accent = colors.HexColor("#1a56db")
    muted = colors.HexColor("#64748b")

    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=accent, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=accent, spaceBefore=12, spaceAfter=4)
    body = styles["Normal"]

    story = []
    story.append(Paragraph("Laporan Peserta PKL", h1))
    story.append(Paragraph(f"Dicetak: {datetime.now().strftime('%d %B %Y %H:%M')}", ParagraphStyle("muted", parent=body, textColor=muted)))
    story.append(HRFlowable(width="100%", thickness=1, color=accent, spaceAfter=8))

    nama = participant.nama_lengkap if participant else target.username
    jurusan = participant.jurusan if participant else "-"
    instansi = participant.instansi if participant else "-"
    mulai = participant.tanggal_mulai.strftime("%d/%m/%Y") if participant and participant.tanggal_mulai else "-"
    selesai = participant.tanggal_selesai.strftime("%d/%m/%Y") if participant and participant.tanggal_selesai else "-"

    story.append(Paragraph("Identitas Peserta", h2))
    info_data = [
        ["Nama Lengkap", nama],
        ["Username", target.username],
        ["Email", target.email],
        ["Jurusan", jurusan],
        ["Instansi", instansi],
        ["Periode PKL", f"{mulai} – {selesai}"],
    ]
    info_tbl = Table(info_data, colWidths=[4*cm, 12*cm])
    info_tbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), muted),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f5f9ff")]),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1e0f4")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2eef9")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(info_tbl)

    story.append(Paragraph(f"Rekap Absensi ({len(attendances)} data)", h2))
    if attendances:
        att_header = [["No", "Tanggal", "Check-in", "Check-out", "Status", "Confidence"]]
        att_rows = [[
            str(i + 1),
            a.attendance_date.strftime("%d/%m/%Y") if a.attendance_date else "-",
            a.check_in_time.strftime("%H:%M") if a.check_in_time else "-",
            a.check_out_time.strftime("%H:%M") if a.check_out_time else "-",
            a.status or "-",
            f"{a.confidence_score:.2f}" if a.confidence_score else "-",
        ] for i, a in enumerate(attendances)]
        att_tbl = Table(att_header + att_rows, colWidths=[1*cm, 3*cm, 2.5*cm, 2.5*cm, 3*cm, 3*cm])
        att_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), accent),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f9ff")]),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1e0f4")),
            ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#e2eef9")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(att_tbl)
    else:
        story.append(Paragraph("Belum ada data absensi.", body))

    story.append(Paragraph(f"Jurnal Kegiatan ({len(journals)} entri)", h2))
    if journals:
        jrn_header = [["No", "Tanggal", "Kegiatan", "Output", "Status"]]
        jrn_rows = [[
            str(i + 1),
            j.tanggal.strftime("%d/%m/%Y") if j.tanggal else "-",
            Paragraph(j.kegiatan[:80], ParagraphStyle("small", parent=body, fontSize=8)),
            Paragraph((j.output or "-")[:60], ParagraphStyle("small", parent=body, fontSize=8)),
            j.status or "-",
        ] for i, j in enumerate(journals)]
        jrn_tbl = Table(jrn_header + jrn_rows, colWidths=[1*cm, 2.5*cm, 6*cm, 4.5*cm, 2*cm])
        jrn_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), accent),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (0, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f9ff")]),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1e0f4")),
            ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#e2eef9")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(jrn_tbl)
    else:
        story.append(Paragraph("Belum ada jurnal kegiatan.", body))

    avg_nilai = sum(a.nilai for a in assessments) / len(assessments) if assessments else 0
    story.append(Paragraph(f"Penilaian ({len(assessments)} entri, rata-rata: {avg_nilai:.1f})", h2))
    if assessments:
        asmnt_header = [["No", "Nilai", "Catatan"]]
        asmnt_rows = [[str(i + 1), str(a.nilai), Paragraph(a.catatan or "-", ParagraphStyle("small", parent=body, fontSize=8))] for i, a in enumerate(assessments)]
        asmnt_tbl = Table(asmnt_header + asmnt_rows, colWidths=[1*cm, 3*cm, 12*cm])
        asmnt_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), accent),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f9ff")]),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1e0f4")),
            ("INNERGRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#e2eef9")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(asmnt_tbl)
    else:
        story.append(Paragraph("Belum ada data penilaian.", body))

    doc.build(story)
    output.seek(0)
    safe_name = target.username.replace(" ", "_")
    filename = f"laporan-{safe_name}-{datetime.now().strftime('%Y%m%d')}.pdf"
    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/peserta/{user_id}/sertifikat")
def export_sertifikat_pkl(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> StreamingResponse:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle

    requester = get_request_user(request, db, authorization)
    if requester.role not in {"admin", "pembimbing"} and requester.id != user_id:
        raise HTTPException(status_code=403, detail="Akses ditolak")

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan")

    participant = db.query(Participant).filter(Participant.user_id == user_id).first()
    assessments = db.query(Assessment).filter(Assessment.user_id == user_id).all()
    total_absen = db.query(Attendance).filter(Attendance.user_id == user_id).count()
    total_hadir = db.query(Attendance).filter(Attendance.user_id == user_id, Attendance.status == "hadir").count()
    total_jurnal = db.query(Journal).filter(Journal.user_id == user_id).count()

    avg_nilai = round(sum(a.nilai for a in assessments) / len(assessments), 1) if assessments else 0
    nama = participant.nama_lengkap if participant else target.username
    instansi = participant.instansi if participant else "-"
    mulai = participant.tanggal_mulai.strftime("%d %B %Y") if participant and participant.tanggal_mulai else "-"
    selesai = participant.tanggal_selesai.strftime("%d %B %Y") if participant and participant.tanggal_selesai else "-"

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4),
                            leftMargin=2.5*cm, rightMargin=2.5*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    gold = colors.HexColor("#d97706")
    navy = colors.HexColor("#1e3a5f")
    indigo = colors.HexColor("#6366f1")

    center_xl = ParagraphStyle("cxl", parent=styles["Normal"], alignment=1, fontSize=28, fontName="Helvetica-Bold", textColor=navy, leading=34)
    center_lg = ParagraphStyle("clg", parent=styles["Normal"], alignment=1, fontSize=15, textColor=navy, leading=20)
    center_md = ParagraphStyle("cmd", parent=styles["Normal"], alignment=1, fontSize=12, textColor=colors.HexColor("#334155"), leading=16)
    center_sm = ParagraphStyle("csm", parent=styles["Normal"], alignment=1, fontSize=9, textColor=colors.HexColor("#64748b"), leading=13)
    name_style = ParagraphStyle("nm", parent=styles["Normal"], alignment=1, fontSize=30, fontName="Helvetica-BoldOblique", textColor=indigo, leading=36)

    story = []
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=3, color=gold, spaceAfter=6))
    story.append(HRFlowable(width="100%", thickness=1, color=gold, spaceAfter=12))

    story.append(Paragraph("SERTIFIKAT PENYELESAIAN", center_xl))
    story.append(Paragraph("Praktik Kerja Lapangan (PKL)", center_lg))
    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="60%", thickness=0.5, color=colors.HexColor("#cbd5e1")))
    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph("Diberikan kepada", center_md))
    story.append(Spacer(1, 0.25*cm))
    story.append(Paragraph(nama, name_style))
    story.append(Spacer(1, 0.3*cm))

    detail_data = [
        ["Instansi PKL", ":", instansi],
        ["Periode", ":", f"{mulai}  –  {selesai}"],
        ["Total Absensi", ":", f"{total_hadir} hadir dari {total_absen} hari"],
        ["Total Jurnal", ":", f"{total_jurnal} entri"],
        ["Nilai Rata-rata", ":", f"{avg_nilai}"],
    ]
    detail_tbl = Table(detail_data, colWidths=[4*cm, 0.5*cm, 10*cm], hAlign="CENTER")
    detail_tbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#475569")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (2, 0), (2, -1), navy),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(detail_tbl)
    story.append(Spacer(1, 0.6*cm))

    story.append(HRFlowable(width="60%", thickness=0.5, color=colors.HexColor("#cbd5e1")))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph("Diterbitkan oleh Dinas Komunikasi dan Informatika Kabupaten Batu Bara", center_sm))
    story.append(Paragraph(f"Tanggal cetak: {datetime.now().strftime('%d %B %Y')}", center_sm))
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=gold, spaceBefore=6))
    story.append(HRFlowable(width="100%", thickness=3, color=gold))

    doc.build(story)
    output.seek(0)
    safe = nama.replace(" ", "_")
    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=sertifikat-pkl-{safe}.pdf"},
    )


@router.get("/analytics/trend")
def get_attendance_trend(
    request: Request,
    days: int = 7,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict:
    from sqlalchemy import func as sqlfunc
    from datetime import date, timedelta

    requester = get_request_user(request, db, authorization)
    today = date.today()
    result = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        count = db.query(Attendance).filter(
            sqlfunc.date(Attendance.attendance_date) == d
        ).count()
        hadir = db.query(Attendance).filter(
            sqlfunc.date(Attendance.attendance_date) == d,
            Attendance.status == "hadir",
        ).count()
        result.append({"date": d.isoformat(), "label": d.strftime("%d/%m"), "total": count, "hadir": hadir})
    return {"data": result}


@router.get("/rekap/csv")
def export_rekap_csv(
    request: Request,
    review_filter: str = Query(default="all"),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> StreamingResponse:
    """Official recap CSV: per-peserta attendance + journal + assessment summary."""
    import csv
    from io import StringIO

    requester = get_request_user(request, db, authorization)
    ensure_admin(requester)

    peserta_list = db.query(User).filter(User.role == "peserta", User.is_active == True).all()
    out = StringIO()
    writer = csv.writer(out)
    writer.writerow(["No", "Nama", "Username", "Jurusan", "Instansi",
                     "Periode Mulai", "Periode Selesai",
                     "Total Absensi", "Hadir", "Terlambat", "Izin",
                     "Review Pending", "Review Approved", "Review Rejected", "Alasan Grace", "Alasan Risk",
                     "Total Jurnal", "Jurnal Disetujui",
                     "Rata-rata Nilai"])

    for i, p in enumerate(peserta_list, 1):
        part = db.query(Participant).filter(Participant.user_id == p.id).first()
        att_query = db.query(Attendance).filter(Attendance.user_id == p.id)
        att_query = apply_attendance_review_filter(att_query, review_filter)
        atts = att_query.all()
        jrns = db.query(Journal).filter(Journal.user_id == p.id).all()
        from app.models.assessment import Assessment as _Asmnt
        asmts = db.query(_Asmnt).filter(_Asmnt.user_id == p.id).all()
        avg = round(sum(a.nilai for a in asmts) / len(asmts), 1) if asmts else 0

        writer.writerow([
            i, part.nama_lengkap if part else p.username, p.username,
            part.jurusan if part else "", part.instansi if part else "",
            part.tanggal_mulai.strftime("%d/%m/%Y") if part and part.tanggal_mulai else "",
            part.tanggal_selesai.strftime("%d/%m/%Y") if part and part.tanggal_selesai else "",
            len(atts),
            sum(1 for a in atts if a.status == "hadir"),
            sum(1 for a in atts if a.status == "terlambat"),
            sum(1 for a in atts if a.status == "izin"),
            sum(1 for a in atts if (a.location_review_status or "") == "pending"),
            sum(1 for a in atts if (a.location_review_status or "") == "approved"),
            sum(1 for a in atts if (a.location_review_status or "") == "rejected"),
            sum(1 for a in atts if (a.location_review_reason or "") in {"grace", "grace_and_risk"}),
            sum(1 for a in atts if (a.location_review_reason or "") in {"risk", "grace_and_risk"}),
            len(jrns),
            sum(1 for j in jrns if j.status in {"approved", "disetujui", "valid"}),
            avg,
        ])

    out.seek(0)
    filename = f"rekap-pkl-{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([out.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

