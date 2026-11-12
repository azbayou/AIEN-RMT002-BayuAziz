"""Interactive leave calendar component for personal and team schedules."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

import streamlit as st

from ui.api_client import api_request
from ui_contract import API_PATHS

BULAN_INDONESIA = [
    "",
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
]

HARI_INDONESIA = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def build_calendar_leave_map(requests: list[dict], year: int, month: int) -> dict[date, list[dict]]:
    """Petakan permohonan cuti aktif (approved & pending review) ke tanggal-tanggal dalam bulan tertentu."""
    leave_map: dict[date, list[dict]] = {}
    if not requests:
        return leave_map

    first_day = date(year, month, 1)
    num_days = calendar.monthrange(year, month)[1]
    last_day = date(year, month, num_days)

    for req in requests:
        status = req.get("status", "")
        if status not in ("approved", "pending_manager_review"):
            continue

        raw_start = req.get("start_date")
        raw_end = req.get("end_date")
        if not raw_start or not raw_end:
            continue

        try:
            r_start = date.fromisoformat(str(raw_start))
            r_end = date.fromisoformat(str(raw_end))
        except (ValueError, TypeError):
            continue

        if r_end < first_day or r_start > last_day:
            continue

        eff_start = max(r_start, first_day)
        eff_end = min(r_end, last_day)

        curr = eff_start
        while curr <= eff_end:
            if curr not in leave_map:
                leave_map[curr] = []
            leave_map[curr].append({
                "request_id": req.get("request_id"),
                "employee_id": req.get("employee_id"),
                "employee_name": req.get("employee_name") or req.get("employee_id"),
                "leave_type": req.get("leave_type", "annual"),
                "status": status,
                "business_days": req.get("business_days", 1),
                "reason": req.get("reason", "-"),
                "start_date": str(raw_start),
                "end_date": str(raw_end),
            })
            curr += timedelta(days=1)

    return leave_map


def render_tab_calendar(token: str, persona: dict, is_manager: bool, is_admin: bool) -> None:
    """Komponen tampilan kalender jadwal cuti interaktif (tim & personal)."""
    st.subheader("Kalender Jadwal Cuti")
    st.caption("Visualisasi jadwal cuti aktif, distribusi ketidakhadiran tim, dan pemantauan permohonan bulanan.")

    today = date.today()
    if "cal_year" not in st.session_state:
        st.session_state["cal_year"] = today.year
    if "cal_month" not in st.session_state:
        st.session_state["cal_month"] = today.month
    if "sel_cal_m_widget" not in st.session_state:
        st.session_state["sel_cal_m_widget"] = BULAN_INDONESIA[st.session_state["cal_month"]]
    if "sel_cal_y_widget" not in st.session_state:
        st.session_state["sel_cal_y_widget"] = st.session_state["cal_year"]

    def _prev_cal_month() -> None:
        if st.session_state["cal_month"] == 1:
            st.session_state["cal_month"] = 12
            st.session_state["cal_year"] -= 1
        else:
            st.session_state["cal_month"] -= 1
        st.session_state["sel_cal_m_widget"] = BULAN_INDONESIA[st.session_state["cal_month"]]
        st.session_state["sel_cal_y_widget"] = st.session_state["cal_year"]

    def _next_cal_month() -> None:
        if st.session_state["cal_month"] == 12:
            st.session_state["cal_month"] = 1
            st.session_state["cal_year"] += 1
        else:
            st.session_state["cal_month"] += 1
        st.session_state["sel_cal_m_widget"] = BULAN_INDONESIA[st.session_state["cal_month"]]
        st.session_state["sel_cal_y_widget"] = st.session_state["cal_year"]

    def _today_cal_month() -> None:
        t = date.today()
        st.session_state["cal_year"] = t.year
        st.session_state["cal_month"] = t.month
        st.session_state["sel_cal_m_widget"] = BULAN_INDONESIA[t.month]
        st.session_state["sel_cal_y_widget"] = t.year

    def _on_cal_month_change() -> None:
        m_name = st.session_state.get("sel_cal_m_widget")
        if m_name in BULAN_INDONESIA:
            st.session_state["cal_month"] = BULAN_INDONESIA.index(m_name)

    def _on_cal_year_change() -> None:
        st.session_state["cal_year"] = int(st.session_state.get("sel_cal_y_widget", date.today().year))

    # Scope Selection (Manager/Admin: Team or Personal; Employee: Personal Only per HR-PRIV-001)
    if is_manager or is_admin:
        col_scope, col_refresh = st.columns([3, 1])
        with col_scope:
            cal_scope = st.radio(
                "Cakupan Kalender:",
                options=["Kalender Tim & Departemen", "Kalender Cuti Saya"],
                horizontal=True,
                key="cal_scope_radio",
            )
        with col_refresh:
            st.write("")
            if st.button("Segarkan Kalender", key="btn_refresh_cal", use_container_width=True):
                st.rerun()

        if cal_scope.startswith("Kalender Tim"):
            raw_requests = api_request("GET", "/api/v1/manager/leave-requests", token) or []
        else:
            raw_requests = api_request("GET", API_PATHS["my_requests"], token) or []
    else:
        col_info, col_refresh = st.columns([3, 1])
        with col_info:
            st.info("[MODE PRIVASI AKTIF] Anda sedang melihat jadwal cuti pribadi Anda sesuai kebijakan perlindungan data (HR-PRIV-001).")
        with col_refresh:
            if st.button("Segarkan Kalender", key="btn_refresh_cal_emp", use_container_width=True):
                st.rerun()
        raw_requests = api_request("GET", API_PATHS["my_requests"], token) or []
        cal_scope = "Kalender Cuti Saya"

    # Navigation Controls: Prev, Month Select, Year Select, Next, Today
    col_prev, col_m_sel, col_y_sel, col_next, col_today = st.columns([0.8, 1.6, 1.2, 0.8, 1.2])
    with col_prev:
        st.button("Sebelumnya", key="btn_cal_prev", help="Bulan Sebelumnya", on_click=_prev_cal_month, use_container_width=True)
    with col_m_sel:
        m_options = BULAN_INDONESIA[1:]
        st.selectbox(
            "Pilih Bulan",
            options=m_options,
            key="sel_cal_m_widget",
            on_change=_on_cal_month_change,
            label_visibility="collapsed",
        )
    with col_y_sel:
        cur_y = st.session_state["cal_year"]
        y_list = list(range(min(today.year - 5, cur_y - 1), max(today.year + 5, cur_y + 1) + 1))
        st.selectbox(
            "Pilih Tahun",
            options=y_list,
            key="sel_cal_y_widget",
            on_change=_on_cal_year_change,
            label_visibility="collapsed",
        )
    with col_next:
        st.button("Berikutnya", key="btn_cal_next", help="Bulan Berikutnya", on_click=_next_cal_month, use_container_width=True)
    with col_today:
        st.button("Hari Ini", key="btn_cal_today", on_click=_today_cal_month, use_container_width=True)

    # Filter Controls: Leave Type & Status
    col_fil1, col_fil2 = st.columns(2)
    with col_fil1:
        fil_type = st.selectbox(
            "Filter Jenis Cuti:",
            options=["Semua Jenis Cuti", "Tahunan (Annual)", "Sakit (Sick)", "Orang Tua (Parental)"],
            key="cal_filter_leave_type",
        )
    with col_fil2:
        fil_status = st.selectbox(
            "Filter Status Permohonan:",
            options=["Semua Status Aktif", "Hanya Disetujui (Approved)", "Menunggu Review (Pending)"],
            key="cal_filter_status",
        )

    cal_year = st.session_state["cal_year"]
    cal_month = st.session_state["cal_month"]

    filtered_requests = []
    for r in raw_requests:
        l_type = r.get("leave_type", "")
        if fil_type == "Tahunan (Annual)" and l_type != "annual":
            continue
        if fil_type == "Sakit (Sick)" and l_type != "sick":
            continue
        if fil_type == "Orang Tua (Parental)" and l_type != "parental":
            continue

        l_status = r.get("status", "")
        if fil_status == "Hanya Disetujui (Approved)" and l_status != "approved":
            continue
        if fil_status == "Menunggu Review (Pending)" and l_status != "pending_manager_review":
            continue

        filtered_requests.append(r)

    leave_map = build_calendar_leave_map(filtered_requests, cal_year, cal_month)

    cal_obj = calendar.Calendar(firstweekday=0)
    month_weeks = cal_obj.monthdatescalendar(cal_year, cal_month)

    cells_html = []
    for week in month_weeks:
        for d in week:
            if d.month != cal_month:
                cells_html.append(
                    f'<div class="calendar-cell empty">'
                    f'<div class="calendar-cell-date" style="color: var(--text-muted); opacity: 0.4;">{d.day}</div>'
                    f'</div>'
                )
            else:
                is_today = (d == today)
                is_weekend = (d.weekday() >= 5)

                cell_cls = ["calendar-cell"]
                if is_today:
                    cell_cls.append("today")
                elif is_weekend:
                    cell_cls.append("weekend")

                d_cls = ["calendar-cell-date"]
                if is_today:
                    d_cls.append("today-badge")
                elif is_weekend:
                    d_cls.append("weekend-text")

                today_badge_html = "<span style='font-size:0.65rem; background: var(--accent-orange-hover); color:#ffffff; padding:1px 5px; border-radius:4px; font-weight:700;'>HARI INI</span>" if is_today else ""

                d_leaves = leave_map.get(d, [])
                badges_html = []
                max_show = 2 if len(d_leaves) > 3 else len(d_leaves)

                type_meta = {
                    "annual": ("annual", "Tahunan"),
                    "sick": ("sick", "Sakit"),
                    "parental": ("parental", "Parental"),
                }

                for l_item in d_leaves[:max_show]:
                    lt_code, lt_label = type_meta.get(l_item["leave_type"], ("annual", "Tahunan"))
                    is_pend = (l_item["status"] == "pending_manager_review")
                    badge_cls = f"calendar-badge calendar-badge-{lt_code}" + (" pending" if is_pend else "")

                    emp_name = l_item.get("employee_name", l_item.get("employee_id"))
                    if cal_scope.startswith("Kalender Tim"):
                        short_name = emp_name.split()[0] if emp_name else "Pegawai"
                        label_txt = f"{short_name} ({lt_label})"
                    else:
                        label_txt = f"Cuti {lt_label}"

                    status_label = "Menunggu Review" if is_pend else "Disetujui"
                    reason_clean = (l_item.get("reason") or "-").replace('"', '&quot;').replace('<', '&lt;')
                    emp_name_clean = str(emp_name).replace('"', '&quot;')

                    tooltip = (
                        f"Pegawai: {emp_name_clean} ({l_item.get('employee_id')})&#10;"
                        f"Jenis: Cuti {lt_label}&#10;"
                        f"Status: {status_label}&#10;"
                        f"Periode: {l_item.get('start_date')} s/d {l_item.get('end_date')} ({l_item.get('business_days')} hari)&#10;"
                        f"Alasan: {reason_clean}"
                    )

                    badges_html.append(f'<div class="{badge_cls}" title="{tooltip}">{label_txt}</div>')

                if len(d_leaves) > max_show:
                    remain_count = len(d_leaves) - max_show
                    other_names = ", ".join(x.get("employee_name", "") for x in d_leaves[max_show:])
                    badges_html.append(
                        f'<div class="calendar-badge" style="background: var(--bg-surface); color: var(--text-muted); font-style:italic;" title="{other_names}">'
                        f'+{remain_count} lainnya...'
                        f'</div>'
                    )

                inner_badges = "".join(badges_html)
                cells_html.append(
                    f'<div class="{" ".join(cell_cls)}">'
                    f'<div class="{" ".join(d_cls)}">'
                    f'<span>{d.day}</span>'
                    f'{today_badge_html}'
                    f'</div>'
                    f'{inner_badges}'
                    f'</div>'
                )

    grid_body = "".join(cells_html)

    first_m_day = date(cal_year, cal_month, 1)
    last_m_day = date(cal_year, cal_month, calendar.monthrange(cal_year, cal_month)[1])
    month_requests = [
        r for r in filtered_requests
        if r.get("start_date") and r.get("end_date")
        and not (
            date.fromisoformat(str(r["end_date"])) < first_m_day
            or date.fromisoformat(str(r["start_date"])) > last_m_day
        )
    ]

    full_cal_html = f"""
    <div class="calendar-container">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
            <div style="font-size: 1.15rem; font-weight: 700; color: var(--accent-orange);">
                {BULAN_INDONESIA[cal_month]} {cal_year}
            </div>
            <div style="font-size: 0.85rem; color: var(--text-muted); font-weight: 500;">
                {len(month_requests)} Pengajuan Aktif pada Bulan Ini
            </div>
        </div>
        <div class="calendar-header-grid">
            <div class="calendar-day-name">Senin</div>
            <div class="calendar-day-name">Selasa</div>
            <div class="calendar-day-name">Rabu</div>
            <div class="calendar-day-name">Kamis</div>
            <div class="calendar-day-name">Jumat</div>
            <div class="calendar-day-name weekend">Sabtu</div>
            <div class="calendar-day-name weekend">Minggu</div>
        </div>
        <div class="calendar-grid">
            {grid_body}
        </div>
        <div class="calendar-legend-box">
            <span style="color: var(--text-muted); font-weight: 700;">Legenda:</span>
            <span style="color: #6ee7b7; font-weight: 600;">Tahunan</span>
            <span style="color: #fda4af; font-weight: 600;">Sakit</span>
            <span style="color: #d8b4fe; font-weight: 600;">Orang Tua</span>
            <span style="border: 1px solid #10b981; padding: 2px 8px; border-radius: 4px; font-size: 0.72rem; color: var(--text-secondary);">Garis Solid: Disetujui</span>
            <span style="border: 1px dashed #fb7185; padding: 2px 8px; border-radius: 4px; font-size: 0.72rem; color: var(--accent-amber);">Garis Putus-putus: Menunggu Review</span>
            <span style="border: 2px solid var(--accent-orange); background: var(--accent-orange-subtle); padding: 2px 8px; border-radius: 4px; font-size: 0.72rem; color: var(--accent-orange);">Hari Ini</span>
        </div>
    </div>
    """
    st.markdown(full_cal_html, unsafe_allow_html=True)

    # Monthly Summary Metrics
    peak_day_str = "Tidak ada"
    max_leaves = 0
    for d, d_list in leave_map.items():
        if len(d_list) > max_leaves:
            max_leaves = len(d_list)
            peak_day_str = f"{d.day} {BULAN_INDONESIA[cal_month]} ({max_leaves} orang)"

    pending_count = sum(1 for r in month_requests if r.get("status") == "pending_manager_review")

    st.markdown("#### Ringkasan Jadwal Cuti Bulan Ini")
    sm1, sm2, sm3, sm4 = st.columns(4)
    sm1.metric("Total Pengajuan Bulan Ini", f"{len(month_requests)} Permohonan")
    sm2.metric("Hari Terisi Cuti", f"{len(leave_map)} Tanggal")
    sm3.metric("Hari Puncak Cuti", peak_day_str)
    sm4.metric("Menunggu Persetujuan", f"{pending_count} Permohonan")

    st.markdown("---")

    # Detailed Drilldown Expander
    with st.expander(f"Rincian Lengkap Permohonan Cuti ({BULAN_INDONESIA[cal_month]} {cal_year}) — {len(month_requests)} data", expanded=False):
        if not month_requests:
            st.info("Tidak ada permohonan cuti aktif pada bulan ini.")
        else:
            for req in month_requests:
                status_raw = req.get("status", "")
                if status_raw == "pending_manager_review":
                    b_html = '<span class="status-badge-pending">Menunggu Review</span>'
                elif status_raw == "approved":
                    b_html = '<span class="status-badge-approved">Disetujui</span>'
                else:
                    b_html = f'<span class="status-badge-cancelled">{status_raw.upper()}</span>'

                emp_label = f"<b>{req.get('employee_name') or req.get('employee_id')}</b> (ID: <code>{req.get('employee_id')}</code>)" if cal_scope.startswith("Kalender Tim") else f"ID: <code>{req.get('request_id')}</code>"
                st.markdown(
                    f"""
                    <div style="background-color: var(--bg-surface-elevated); border: 1px solid var(--border-subtle); border-radius: 8px; padding: 10px 14px; margin-bottom: 8px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <div style="font-size: 0.95rem; color: var(--text-primary);">
                                {emp_label} — Cuti {str(req.get('leave_type', '')).capitalize()}
                            </div>
                            <div>{b_html}</div>
                        </div>
                        <div style="color: var(--text-secondary); font-size: 0.88rem;">
                            <b>Rentang:</b> {req.get('start_date')} s/d {req.get('end_date')} ({req.get('business_days')} hari kerja)
                            | <b>Alasan:</b> <i>"{req.get('reason', '-')}"</i>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
