"""Operational Monitoring and SLI/SLA Audit tab for Admin role."""
from __future__ import annotations

import streamlit as st

from ui.api_client import api_request
from ui_contract import API_PATHS


def render_tab_monitoring(token: str) -> None:
    """Render Tab 5: Operational Monitoring & Audit Telemetry."""
    st.subheader("Ringkasan Telemetry dan Audit Operasional")
    st.caption("Metrik agregat, monitoring ambang batas SLI/SLA, dan alert tindakan operasional.")

    col_mon_sync, _ = st.columns([1, 4])
    with col_mon_sync:
        if st.button("Segarkan Metrik", key="btn_refresh_mon", use_container_width=True):
            st.rerun()

    summary = api_request("GET", API_PATHS["monitoring_summary"], token)
    alerts = api_request("GET", API_PATHS["monitoring_alerts"], token)
    admin_analytics = api_request("GET", "/api/v1/analytics/overview", token)

    if admin_analytics:
        st.markdown("#### Analitik SDM Tingkat Organisasi")
        a_sz = admin_analytics.get("team_size", 0)
        a_req = admin_analytics.get("requests_by_status", {})
        a_days = admin_analytics.get("days_by_leave_type", {})
        a_low = admin_analytics.get("low_balance_employees", [])

        ac1, ac2, ac3, ac4 = st.columns(4)
        ac1.metric("Total Pegawai Terpantau", f"{a_sz} Pegawai")
        ac2.metric("Cuti Menunggu Review", a_req.get("pending_manager_review", 0))
        ac3.metric("Total Hari Cuti Aktif", f"{sum(a_days.values())} Hari")
        ac4.metric("Pegawai Risiko Saldo Rendah", f"{len(a_low)} Pegawai")

        if a_low:
            with st.expander("Pegawai Risiko Saldo Rendah Organisasi (<= 3 Hari)", expanded=False):
                for lb in a_low:
                    st.info(f"**{lb.get('display_name')}** (`{lb.get('employee_id')}`): Sisa Cuti Tahunan **{lb.get('annual_remaining')} hari**")
        st.markdown("---")

    if summary:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Percakapan", summary.get("run_count", 0))
        err_rate = float(summary.get("error_rate", 0.0))
        c2.metric("Tingkat Error", f"{err_rate:.1%}")
        p95 = float(summary.get("p95_latency_ms", 0.0))
        c3.metric("p95 Latency", f"{int(p95)} ms")
        c4.metric("Total Tool Calls", summary.get("tool_calls", 0))

        st.markdown("---")

    if alerts is not None:
        st.subheader("Status Aturan Alert Operasional")
        if not alerts:
            st.success("Seluruh metrik operasional berada di bawah ambang batas normal. Tidak ada alert aktif.")
        else:
            for alert in alerts:
                st.error(
                    f"""
                    **[ALERT AKTIF] Aturan: `{alert.get('rule_id')}`**
                    - **Metrik:** `{alert.get('metric')}` (Nilai saat ini: `{alert.get('current_value')}`, Ambang Batas: `{alert.get('threshold')}`)
                    - **Penanggung Jawab:** `{alert.get('owner')}`
                    - **Prosedur Respons:** {alert.get('response')}
                    """
                )
