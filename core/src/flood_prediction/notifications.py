"""
Notifications module — Twilio SMS alerts + ReportLab PDF report generation.

SMS is sent when risk level is HIGH or CRITICAL.
PDF reports are generated on-demand or auto-triggered on CRITICAL alerts.
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from .settings import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cooldown tracker  (in-memory; keyed by watershed name)
# ---------------------------------------------------------------------------
_sms_last_sent: Dict[str, datetime] = {}   # watershed_name -> last sent time


# ===========================================================================
# SMS  (Twilio)
# ===========================================================================

def _twilio_client():
    """Return a Twilio REST client, or None if credentials are missing."""
    try:
        from twilio.rest import Client
        sid = settings.twilio_account_sid
        token = settings.twilio_auth_token
        if not sid or not token:
            logger.warning("Twilio credentials not configured — SMS disabled.")
            return None
        return Client(sid, token)
    except ImportError:
        logger.error("twilio package not installed.")
        return None


def _is_sms_cooldown(watershed_name: str) -> bool:
    """Return True if a SMS was already sent for this watershed within the cooldown window."""
    last = _sms_last_sent.get(watershed_name)
    if last is None:
        return False
    elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 60
    return elapsed < settings.sms_cooldown_minutes


def send_sms_alert(
    watershed_name: str,
    risk_level: str,
    risk_score: float,
    message: str,
    affected_areas: Optional[List[str]] = None,
) -> bool:
    """
    Send an SMS alert to all configured phone numbers.

    Only fires when:
    - sms_alerts_enabled is True
    - Twilio credentials are present
    - risk_level is HIGH or CRITICAL
    - Cooldown has elapsed for this watershed
    """
    if not settings.sms_alerts_enabled:
        logger.debug("SMS alerts disabled.")
        return False

    # Check risk threshold
    risk_upper = risk_level.upper()
    if risk_upper not in ("HIGH", "CRITICAL"):
        return False

    if _is_sms_cooldown(watershed_name):
        logger.info(f"SMS cooldown active for {watershed_name} — skipping.")
        return False

    client = _twilio_client()
    if client is None:
        return False

    from_number = settings.twilio_from_number
    if not from_number:
        logger.error("TWILIO_FROM_NUMBER not configured.")
        return False

    # Build SMS body (keep under 160 chars for single SMS)
    areas_str = ""
    if affected_areas:
        areas_str = f"\nAreas: {', '.join(affected_areas[:3])}"
        if len(affected_areas) > 3:
            areas_str += f" +{len(affected_areas) - 3} more"

    sms_body = (
        f"🌊 FLOOD ALERT [{risk_upper}]\n"
        f"Site: {watershed_name}\n"
        f"Risk Score: {risk_score:.1f}/10\n"
        f"{message[:100]}"
        f"{areas_str}\n"
        f"Time: {datetime.now(timezone.utc).strftime('%d-%b-%Y %H:%M UTC')}\n"
        f"NDMA Helpline: 1078"
    )

    success = True
    numbers = settings.sms_alert_numbers or []
    for number in numbers:
        try:
            msg = client.messages.create(
                body=sms_body,
                from_=from_number,
                to=number,
            )
            logger.info(f"SMS sent to {number} — SID: {msg.sid}")
        except Exception as exc:
            logger.error(f"Failed to send SMS to {number}: {exc}")
            success = False

    if success:
        _sms_last_sent[watershed_name] = datetime.now(timezone.utc)

    return success


def send_bulk_sms_summary(
    critical_watersheds: List[Dict[str, Any]],
    overall_risk: str,
) -> bool:
    """
    Send a single consolidated SMS when multiple watersheds are critical.
    Used for scheduled summary alerts.
    """
    if not settings.sms_alerts_enabled:
        return False
    if not critical_watersheds:
        return False

    client = _twilio_client()
    if client is None:
        return False

    from_number = settings.twilio_from_number
    if not from_number:
        return False

    site_lines = "\n".join(
        f"• {w['name']} ({w.get('risk_score', 0):.1f}/10)"
        for w in critical_watersheds[:5]
    )
    extra = f"\n+{len(critical_watersheds) - 5} more sites" if len(critical_watersheds) > 5 else ""

    body = (
        f"🌊 FLOOD SUMMARY [{overall_risk}]\n"
        f"{len(critical_watersheds)} sites at risk:\n"
        f"{site_lines}{extra}\n"
        f"{datetime.now(timezone.utc).strftime('%d-%b-%Y %H:%M UTC')}\n"
        f"NDMA: 1078 | NDRF: 011-24363260"
    )

    numbers = settings.sms_alert_numbers or []
    for number in numbers:
        try:
            client.messages.create(body=body, from_=from_number, to=number)
            logger.info(f"Summary SMS sent to {number}")
        except Exception as exc:
            logger.error(f"Failed summary SMS to {number}: {exc}")

    return True


# ===========================================================================
# PDF Report  (ReportLab)
# ===========================================================================

def generate_flood_report(
    watersheds: List[Dict[str, Any]],
    alerts: Optional[List[Dict[str, Any]]] = None,
    report_title: str = "India Flood Intelligence Report",
    include_charts: bool = True,
) -> Optional[Path]:
    """
    Generate a PDF flood risk report and save it to the reports directory.

    Returns the Path of the saved PDF, or None on failure.
    """
    if not settings.pdf_reports_enabled:
        logger.warning("PDF reports disabled.")
        return None

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            HRFlowable, KeepTogether,
        )
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    except ImportError:
        logger.error("reportlab not installed — cannot generate PDF.")
        return None

    # ── File path ──────────────────────────────────────────────────────────
    reports_dir = Path(settings.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    pdf_path = reports_dir / f"flood_report_{timestamp}.pdf"

    # ── Styles ─────────────────────────────────────────────────────────────
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "Title",
        parent=styles["Title"],
        fontSize=20,
        textColor=colors.HexColor("#1a3a5c"),
        spaceAfter=6,
        alignment=TA_CENTER,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#555555"),
        spaceAfter=4,
        alignment=TA_CENTER,
    )
    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontSize=13,
        textColor=colors.HexColor("#1a3a5c"),
        spaceBefore=14,
        spaceAfter=6,
        borderPad=4,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=9,
        leading=14,
        textColor=colors.HexColor("#333333"),
    )
    alert_style = ParagraphStyle(
        "Alert",
        parent=styles["Normal"],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#cc0000"),
    )
    footer_style = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#888888"),
        alignment=TA_CENTER,
    )

    # ── Helpers ────────────────────────────────────────────────────────────
    def risk_color(level: str) -> colors.Color:
        level = (level or "").upper()
        if level == "CRITICAL":
            return colors.HexColor("#8B0000")
        if level in ("HIGH", "HIGH"):
            return colors.HexColor("#cc0000")
        if level == "MODERATE":
            return colors.HexColor("#e67e00")
        return colors.HexColor("#1a7a1a")

    def risk_bg(level: str) -> colors.Color:
        level = (level or "").upper()
        if level == "CRITICAL":
            return colors.HexColor("#ffe0e0")
        if level in ("HIGH",):
            return colors.HexColor("#fff0e0")
        if level == "MODERATE":
            return colors.HexColor("#fffbe6")
        return colors.HexColor("#f0fff0")

    # ── Compute summary stats ──────────────────────────────────────────────
    total_sites = len(watersheds)
    critical_count = sum(1 for w in watersheds if w.get("risk_score", 0) >= 8)
    high_count = sum(1 for w in watersheds if 6 <= w.get("risk_score", 0) < 8)
    moderate_count = sum(1 for w in watersheds if 4 <= w.get("risk_score", 0) < 6)
    low_count = total_sites - critical_count - high_count - moderate_count
    avg_score = (
        sum(w.get("risk_score", 0) for w in watersheds) / total_sites
        if total_sites else 0
    )
    overall_level = (
        "CRITICAL" if avg_score >= 8
        else "HIGH" if avg_score >= 6
        else "MODERATE" if avg_score >= 4
        else "LOW"
    )

    # Sort watersheds: highest risk first
    sorted_ws = sorted(watersheds, key=lambda w: w.get("risk_score", 0), reverse=True)

    # ── Build PDF elements ─────────────────────────────────────────────────
    elements = []
    now_str = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")

    # Header
    elements.append(Paragraph(report_title, title_style))
    elements.append(Paragraph(f"Generated: {now_str}", subtitle_style))
    elements.append(Paragraph(
        "India Flood Intelligence System · Open-Meteo GloFAS · NVIDIA AI",
        subtitle_style,
    ))
    elements.append(HRFlowable(width="100%", thickness=2,
                                color=colors.HexColor("#1a3a5c"), spaceAfter=10))

    # ── Executive Summary ──────────────────────────────────────────────────
    elements.append(Paragraph("Executive Summary", section_style))

    summary_data = [
        ["Metric", "Value"],
        ["Overall Risk Level", overall_level],
        ["Average Risk Score", f"{avg_score:.1f} / 10"],
        ["Total Monitoring Sites", str(total_sites)],
        ["Critical Sites (≥8.0)", str(critical_count)],
        ["High Risk Sites (6–8)", str(high_count)],
        ["Moderate Sites (4–6)", str(moderate_count)],
        ["Low Risk Sites (<4)", str(low_count)],
        ["Report Generated", now_str],
    ]
    summary_table = Table(summary_data, colWidths=[8 * cm, 9 * cm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 1), (-1, 1), risk_bg(overall_level)),
        ("TEXTCOLOR",  (1, 1), (1, 1), risk_color(overall_level)),
        ("FONTNAME",   (1, 1), (1, 1), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 2), (-1, -1),
         [colors.HexColor("#f7f9fc"), colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 0.3 * cm))

    # ── Active Alerts ──────────────────────────────────────────────────────
    if alerts:
        elements.append(Paragraph("Active Alerts", section_style))
        for alert in alerts[:10]:
            severity = alert.get("severity", "")
            a_type = alert.get("alert_type", alert.get("title", "Alert"))
            a_msg = alert.get("message", "")
            a_area = alert.get("affected_counties", alert.get("watershed_name", ""))
            elements.append(KeepTogether([
                Paragraph(
                    f"<b>[{severity.upper()}]</b> {a_type} — {a_area}",
                    alert_style,
                ),
                Paragraph(a_msg[:200], body_style),
                Spacer(1, 0.15 * cm),
            ]))

    # ── Watershed Risk Table ───────────────────────────────────────────────
    elements.append(Paragraph("Watershed Risk Status", section_style))

    ws_headers = ["Watershed", "Region", "Risk Level", "Score", "Flow (CFS)", "Trend", "Source"]
    ws_rows = [ws_headers]
    for w in sorted_ws:
        score = w.get("risk_score", 0)
        level = w.get("current_risk_level", "Low")
        ws_rows.append([
            w.get("name", "—")[:28],
            (w.get("region", "—") or "—")[:18],
            level.upper(),
            f"{score:.1f}",
            f"{w.get('current_streamflow_cfs', 0):,.0f}",
            (w.get("trend", "stable") or "stable").capitalize(),
            (w.get("data_source", "—") or "—").upper(),
        ])

    col_widths = [5.5*cm, 3.5*cm, 2.5*cm, 1.5*cm, 2.5*cm, 2*cm, 2*cm]
    ws_table = Table(ws_rows, colWidths=col_widths, repeatRows=1)

    # Build per-row color styles
    row_styles = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 8),
        ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
    ]
    for row_idx, w in enumerate(sorted_ws, start=1):
        score = w.get("risk_score", 0)
        level = w.get("current_risk_level", "Low").upper()
        if score >= 8 or level == "CRITICAL":
            row_styles.append(("BACKGROUND", (0, row_idx), (-1, row_idx),
                                colors.HexColor("#ffe0e0")))
            row_styles.append(("TEXTCOLOR", (2, row_idx), (3, row_idx),
                                colors.HexColor("#8B0000")))
            row_styles.append(("FONTNAME", (2, row_idx), (3, row_idx),
                                "Helvetica-Bold"))
        elif score >= 6:
            row_styles.append(("BACKGROUND", (0, row_idx), (-1, row_idx),
                                colors.HexColor("#fff4e0")))
            row_styles.append(("TEXTCOLOR", (2, row_idx), (3, row_idx),
                                colors.HexColor("#cc6600")))
        elif score >= 4:
            row_styles.append(("BACKGROUND", (0, row_idx), (-1, row_idx),
                                colors.HexColor("#fffbe6")))

    ws_table.setStyle(TableStyle(row_styles))
    elements.append(ws_table)
    elements.append(Spacer(1, 0.4 * cm))

    # ── Critical Sites Detail ──────────────────────────────────────────────
    critical_sites = [w for w in sorted_ws if w.get("risk_score", 0) >= 6]
    if critical_sites:
        elements.append(Paragraph("High & Critical Site Details", section_style))
        for w in critical_sites[:10]:
            score = w.get("risk_score", 0)
            level = w.get("current_risk_level", "Low").upper()
            flood_stage = w.get("flood_stage_cfs", 0) or 0
            current_flow = w.get("current_streamflow_cfs", 0) or 0
            ratio = (current_flow / flood_stage * 100) if flood_stage else 0
            trend_rate = w.get("trend_rate_cfs_per_hour", 0) or 0

            detail_data = [
                [Paragraph(f"<b>{w.get('name', '—')}</b>  [{level}  {score:.1f}/10]",
                           body_style), ""],
                ["Region", w.get("region", "—")],
                ["Current Flow", f"{current_flow:,.0f} CFS"],
                ["Flood Stage",  f"{flood_stage:,.0f} CFS"],
                ["Flow / Stage", f"{ratio:.1f}%"],
                ["Trend Rate",   f"{trend_rate:+.0f} CFS/hr"],
                ["Data Source",  (w.get("data_source") or "—").upper()],
                ["Last Updated", w.get("last_updated", "—")[:19]],
            ]
            detail_table = Table(detail_data, colWidths=[5*cm, 12.5*cm])
            detail_table.setStyle(TableStyle([
                ("SPAN",       (0, 0), (-1, 0)),
                ("BACKGROUND", (0, 0), (-1, 0), risk_bg(level)),
                ("FONTNAME",   (0, 1), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE",   (0, 0), (-1, -1), 8),
                ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
                ("TOPPADDING",    (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ]))
            elements.append(KeepTogether([detail_table, Spacer(1, 0.3 * cm)]))

    # ── Recommendations ────────────────────────────────────────────────────
    elements.append(Paragraph("Recommendations", section_style))
    rec_lines = _build_recommendations(overall_level, critical_count, high_count)
    for line in rec_lines:
        elements.append(Paragraph(f"• {line}", body_style))
        elements.append(Spacer(1, 0.1 * cm))

    # ── Emergency Contacts ─────────────────────────────────────────────────
    elements.append(Spacer(1, 0.3 * cm))
    elements.append(HRFlowable(width="100%", thickness=1,
                                color=colors.HexColor("#cccccc")))
    contacts = [
        ["Agency", "Contact"],
        ["NDMA National Helpline", "1078"],
        ["NDRF",                   "011-24363260"],
        ["IMD Weather",            "mausam.imd.gov.in"],
        ["CWC Flood Forecast",     "cwc.gov.in"],
        ["NDMA SACHET",            "sachet.ndma.gov.in"],
    ]
    contact_table = Table(contacts, colWidths=[9*cm, 9*cm])
    contact_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.HexColor("#f7f9fc"), colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
    ]))
    elements.append(Spacer(1, 0.2 * cm))
    elements.append(Paragraph("Emergency Contacts", section_style))
    elements.append(contact_table)

    # ── Footer ─────────────────────────────────────────────────────────────
    elements.append(Spacer(1, 0.4 * cm))
    elements.append(Paragraph(
        "This report is auto-generated by India Flood Intelligence System. "
        "Data sourced from Open-Meteo GloFAS (free, no key required). "
        "AI analysis powered by NVIDIA NIM. For emergencies dial NDMA helpline 1078.",
        footer_style,
    ))

    # ── Build PDF ──────────────────────────────────────────────────────────
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=report_title,
        author="India Flood Intelligence System",
        subject="Flood Risk Report",
    )

    try:
        doc.build(elements)
        logger.info(f"PDF report generated: {pdf_path}")
        return pdf_path
    except Exception as exc:
        logger.error(f"PDF build failed: {exc}")
        return None


def _build_recommendations(level: str, critical: int, high: int) -> List[str]:
    """Return context-aware recommendations based on risk level."""
    recs = []
    level = level.upper()

    if level == "CRITICAL":
        recs += [
            "IMMEDIATE ACTION REQUIRED — Deploy NDRF battalions to critical zones.",
            "Issue mandatory evacuation orders for low-lying areas near critical sites.",
            "Activate all NDMA/State DMA emergency operation centres.",
            "Broadcast continuous alerts via Doordarshan, AIR, and SACHET platform.",
            "Pre-position rescue boats and emergency supplies at identified staging areas.",
        ]
    elif level == "HIGH":
        recs += [
            "Place NDRF teams on standby for rapid deployment.",
            "Issue voluntary evacuation advisories for flood-prone communities.",
            "Activate district-level emergency management teams.",
            "Coordinate with IMD for updated 24–48h rainfall forecasts.",
            "Inspect and reinforce embankments at high-risk sites.",
        ]
    elif level == "MODERATE":
        recs += [
            "Increase monitoring frequency to every 30 minutes.",
            "Ensure emergency response resources are on standby.",
            "Distribute public advisories through local authorities.",
            "Check that flood control gates and sluices are operational.",
        ]
    else:
        recs += [
            "Continue routine monitoring of river discharge levels.",
            "Review and update emergency response plans.",
            "Conduct community awareness programmes in flood-prone areas.",
        ]

    # Extra for many critical/high sites
    if critical >= 5:
        recs.append(
            f"{critical} sites at CRITICAL level — consider regional disaster declaration."
        )
    if high + critical >= 10:
        recs.append(
            "Wide-area flood event likely — coordinate with Central Water Commission."
        )

    return recs


def list_reports() -> List[Dict[str, Any]]:
    """Return metadata of all PDF reports in the reports directory."""
    reports_dir = Path(settings.reports_dir)
    if not reports_dir.exists():
        return []

    result = []
    for f in sorted(reports_dir.glob("flood_report_*.pdf"), reverse=True):
        stat = f.stat()
        result.append({
            "filename": f.name,
            "path": str(f),
            "size_kb": round(stat.st_size / 1024, 1),
            "created_at": datetime.fromtimestamp(
                stat.st_ctime, tz=timezone.utc
            ).isoformat(),
        })
    return result
