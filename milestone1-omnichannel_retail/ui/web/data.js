/* ==========================================================================
   Omnichannel Retail Lakehouse — Static Verified Snapshot, Code & Bilingual Copy
   All schemas, SQL formulas, Python snippets, and metrics are grounded in repo files.
   No credentials or tokens are ever stored in this file.
   ========================================================================== */

(function (global) {
  "use strict";

  const DEFAULTS = {
    workspaceHost: "https://dbc-118afc22-e599.cloud.databricks.com",
    orgId: "7474648823106559",
    jobId: 1033864740434224,
    warehouseId: "d3c4e4657744978e",
    catalog: "retail_analytics",
    verifiedRunId: 647116123722071,
    workspaceUrl: "https://dbc-118afc22-e599.cloud.databricks.com/?o=7474648823106559",
    jobUrl: "https://dbc-118afc22-e599.cloud.databricks.com/?o=7474648823106559#job/1033864740434224",
    verifiedRunUrl:
      "https://dbc-118afc22-e599.cloud.databricks.com/?o=7474648823106559#job/1033864740434224/run/647116123722071",
  };

  const I18N = {
    en: {
      "brand.title": "Omnichannel Retail Lakehouse",
      "nav.stackDatabricks": "Databricks Lakehouse",
      "nav.stackAirflow": "Airflow + Postgres",
      "nav.perspBusiness": "Business Impact",
      "nav.perspEngineer": "Engineer Deep-Dive",
      "nav.openDatabricks": "Open Databricks ↗",
      "nav.runLive": "Run Live on Databricks",
      "auth.liveReady": "Live Cloud Ready",
      "auth.passcodeUnlocked": "Live Cloud Ready (Passcode)",
      "auth.byokConnected": "Live Cloud Ready (BYOK)",
      "auth.locked": "Locked · Unlock Cloud",
      "auth.simulation": "Simulation Mode",
      "hero.eyebrow": "DATABRICKS LAKEFLOW · UNITY CATALOG · ZERO-DRIFT MEDALLION",
      "hero.title": "Production Omnichannel Retail Lakehouse & AI Analytics Control Plane",
      "hero.pitchBusiness":
        "Turns 158,770 chaotic omnichannel events across Web, Store, Mobile App, and Marketplace into an audit-reconciled $13.56M revenue ledger. Every dollar reconciles with $0.00 drift across executive, customer, and refund marts while an AST-safe NL-to-SQL Copilot answers business questions in milliseconds.",
      "hero.pitchEngineer":
        "Dual-orchestrated Medallion Lakehouse running PySpark Delta MERGE pipelines on Databricks Lakeflow Serverless (6 tasks) and PostgreSQL/Airflow locally (7 tasks). Enforces SHA-256 ingestion manifests, deterministic window deduplication, fail-fast Silver/Gold quality gates in ops.quality_checks, and zero fact multiplication.",
      "hero.metaWorkspace": "Workspace",
      "hero.metaJob": "Lakeflow Job",
      "hero.metaWarehouse": "SQL Warehouse",
      "hero.metaCompute": "Compute Profile",
      "ribbon.rawEvents": "Raw Events",
      "ribbon.rawSub": "bronze.raw_records · 19 files",
      "ribbon.silverRows": "Clean Silver Rows",
      "ribbon.silverSub": "Deduplicated · UTC TIMESTAMPTZ",
      "ribbon.rejected": "Rejected Anomaly",
      "ribbon.rejectedSub": "qty <= 0 → silver.rejected_records",
      "ribbon.deltaTables": "Delta Tables",
      "ribbon.deltaSub": "Unity Catalog (1B · 16S · 5G · 3O)",
      "ribbon.drift": "Reconciliation Drift",
      "ribbon.driftSub": "9/9 ops.quality_checks passed",
      "ribbon.benchmark": "NL-to-SQL Benchmark",
      "ribbon.benchmarkSub": "100% Gold query validation",
      "xray.title": "Medallion Architecture & Interactive Record X-Ray",
      "xray.subtitle":
        "Trace real omnichannel orders from raw Volume landing through Bronze immutability, Silver quarantine/deduplication, and Gold 360° valuation.",
      "xray.contractsLabel": "Table Contracts & Guarantees",
      "xray.tablesLabel": "Layer Tables",
      "xray.traceLabel": "Live Record Mutation Trace",
      "dag.title": "Interactive Pipeline DAG & Code Inspector",
      "dag.subtitle":
        "Execute live Databricks Lakeflow serverless tasks, run animated local simulations, or trigger a negative-quantity quality gate failure.",
      "dag.latestRunsLabel": "Latest Runs",
      "dag.simulate": "Simulate Pipeline",
      "dag.testGate": "Test Quality Gate",
      "dag.reset": "Reset",
      "dag.whyRecruiters": "Why Recruiters & Hiring Managers Care",
      "dag.businessImpact": "Business Impact",
      "dag.engineerDeepDive": "Engineering Deep-Dive",
      "dag.telemetryTitle": "LIVE EXECUTION TELEMETRY STREAM (UTC)",
      "dag.clearLog": "Clear",
      "bi.title": "Gold Executive BI & Zero-Drift Reconciliation",
      "bi.subtitle":
        "Verified analytical marts from retail_analytics.gold.* backed by ops.quality_checks parity audits.",
      "bi.sourceSnapshot": "Verified Snapshot",
      "bi.sourceLive": "Live Databricks SQL",
      "bi.refreshBtn": "Refresh Live Metrics",
      "bi.kpiNetRev": "Net Revenue (90d)",
      "bi.kpiOrders": "Total Orders",
      "bi.kpiAov": "Average Order Value",
      "bi.kpiRepeat": "Repeat Customer Rate",
      "bi.trendTitle": "7-Day Net Revenue Trend",
      "bi.channelTitle": "Omnichannel Net Revenue Split",
      "bi.reconTitle": "Financial Reconciliation & Quality Gates",
      "bi.colCheck": "Check Name",
      "bi.colStage": "Gate Stage",
      "bi.colStatus": "Status",
      "bi.colDetails": "Audit Details",
      "copilot.title": "Embedded Gold-Layer NL-to-SQL Analyst",
      "copilot.subtitle":
        "Ask business questions in natural language. Read-only AST-validated SQL executes against Gold contracts with live SVG visualization.",
      "copilot.askBtn": "Analyze Gold",
      "copilot.placeholder": "Ask about omnichannel revenue, categories, ROAS, or stockouts...",
      "copilot.chartLabel": "Visual Insight",
      "copilot.tableLabel": "Result Rows (Click headers to sort)",
      "copilot.sqlToggle": "View Generated Read-Only SQL & Provenance",
      "modal.title": "Connect & Unlock Databricks Execution",
      "modal.tabSso": "SSO / Workspace Portal",
      "modal.tabPasscode": "Demo Passcode",
      "modal.tabCredentials": "Custom Workspace (Host + PAT)",
      "modal.ssoDesc":
        "Databricks enterprise workspaces authenticate interactive users via workspace SSO. Open the hosted workspace or inspect Lakeflow Job #1033864740434224 directly in Databricks.",
      "modal.openWorkspace": "Open Databricks Workspace Login ↗",
      "modal.openJob": "Open Lakeflow Pipeline Job ↗",
      "modal.passcodeDesc":
        "Enter the public demo passcode to unlock server-side HMAC execution against the hosted Databricks workspace. Tokens are kept strictly in sessionStorage for this browser tab.",
      "modal.passcodeLabel": "Demo Passcode",
      "modal.unlockBtn": "Unlock Live Cloud",
      "modal.disconnectBtn": "Disconnect Session",
      "modal.credsDesc":
        "Connect your own Databricks workspace with a Personal Access Token (BYOK). Credentials are verified via Databricks SCIM /Me and stored strictly in sessionStorage (never persisted to disk).",
      "modal.hostLabel": "Workspace Host URL",
      "modal.tokenLabel": "Personal Access Token (PAT)",
      "modal.jobLabel": "Job ID (Optional)",
      "modal.whLabel": "SQL Warehouse ID (Optional)",
      "modal.connectBtn": "Verify & Connect Workspace",
      "common.copy": "Copy",
      "common.copied": "Copied",
    },
    id: {
      "brand.title": "Omnichannel Retail Lakehouse",
      "nav.stackDatabricks": "Databricks Lakehouse",
      "nav.stackAirflow": "Airflow + Postgres",
      "nav.perspBusiness": "Dampak Bisnis",
      "nav.perspEngineer": "Bedah Teknis",
      "nav.openDatabricks": "Buka Databricks ↗",
      "nav.runLive": "Jalankan Live di Databricks",
      "auth.liveReady": "Cloud Siap Live",
      "auth.passcodeUnlocked": "Cloud Siap Live (Passcode)",
      "auth.byokConnected": "Cloud Siap Live (BYOK)",
      "auth.locked": "Terkunci · Buka Akses Cloud",
      "auth.simulation": "Mode Simulasi",
      "hero.eyebrow": "DATABRICKS LAKEFLOW · UNITY CATALOG · MEDALLION TANPA DRIFT",
      "hero.title": "Kontrol Plane Lakehouse Ritel Omnichannel & Analitik AI Produksi",
      "hero.pitchBusiness":
        "Mengubah 158.770 event omnichannel dari Web, Toko Fisik, Mobile App, dan Marketplace menjadi buku besar pendapatan $13,56 juta yang teraudit. Setiap sen terekonsiliasi dengan selisih $0,00 di seluruh tabel eksekutif, pelanggan, dan refund, dilengkapi Copilot NL-to-SQL aman.",
      "hero.pitchEngineer":
        "Arsitektur Medallion Lakehouse ganda menggunakan pipeline PySpark Delta MERGE pada Databricks Lakeflow Serverless (6 task) serta Airflow + PostgreSQL lokal (7 task). Menerapkan manifest SHA-256, deduplikasi window deterministik, quality gate fail-fast di ops.quality_checks, dan bebas fact multiplication.",
      "hero.metaWorkspace": "Workspace",
      "hero.metaJob": "Job Lakeflow",
      "hero.metaWarehouse": "SQL Warehouse",
      "hero.metaCompute": "Profil Komputasi",
      "ribbon.rawEvents": "Event Mentah",
      "ribbon.rawSub": "bronze.raw_records · 19 berkas",
      "ribbon.silverRows": "Baris Silver Bersih",
      "ribbon.silverSub": "Terdeduplikasi · UTC TIMESTAMPTZ",
      "ribbon.rejected": "Anomali Ditolak",
      "ribbon.rejectedSub": "qty <= 0 → silver.rejected_records",
      "ribbon.deltaTables": "Tabel Delta",
      "ribbon.deltaSub": "Unity Catalog (1B · 16S · 5G · 3O)",
      "ribbon.drift": "Selisih Rekonsiliasi",
      "ribbon.driftSub": "9/9 ops.quality_checks lulus",
      "ribbon.benchmark": "Benchmark NL-to-SQL",
      "ribbon.benchmarkSub": "100% validasi kueri Gold",
      "xray.title": "Arsitektur Medallion & X-Ray Mutasi Data Interaktif",
      "xray.subtitle":
        "Lacak perjalanan order omnichannel nyata dari pendaratan Volume mentah, imutabilitas Bronze, karantina/deduplikasi Silver, hingga valuasi Gold 360°.",
      "xray.contractsLabel": "Kontrak Tabel & Jaminan Kualitas",
      "xray.tablesLabel": "Daftar Tabel Layer",
      "xray.traceLabel": "Jejak Mutasi Record Nyata",
      "dag.title": "Kanvas Pipeline DAG Interaktif & Inspektur Kode",
      "dag.subtitle":
        "Eksekusi task serverless Databricks Lakeflow secara live, jalankan simulasi lokal, atau uji kegagalan quality gate kuantitas negatif.",
      "dag.latestRunsLabel": "Eksekusi Terbaru",
      "dag.simulate": "Simulasikan Pipeline",
      "dag.testGate": "Uji Quality Gate",
      "dag.reset": "Reset",
      "dag.whyRecruiters": "Nilai Strategis bagi Rekruter & Tim Data",
      "dag.businessImpact": "Dampak Bisnis",
      "dag.engineerDeepDive": "Pendalaman Rekayasa",
      "dag.telemetryTitle": "ALIRAN TELEMETRI EKSEKUSI LIVE (UTC)",
      "dag.clearLog": "Bersihkan",
      "bi.title": "BI Eksekutif Gold & Rekonsiliasi Zero-Drift",
      "bi.subtitle":
        "Mart analitik terverifikasi dari retail_analytics.gold.* yang dijaga audit paritas ops.quality_checks.",
      "bi.sourceSnapshot": "Snapshot Terverifikasi",
      "bi.sourceLive": "Databricks SQL Live",
      "bi.refreshBtn": "Segarkan Metrik Live",
      "bi.kpiNetRev": "Pendapatan Bersih (90h)",
      "bi.kpiOrders": "Total Pesanan",
      "bi.kpiAov": "Rata-rata Nilai Order",
      "bi.kpiRepeat": "Rasio Pelanggan Ulang",
      "bi.trendTitle": "Tren Pendapatan Bersih 7 Hari",
      "bi.channelTitle": "Porsi Pendapatan per Kanal Omnichannel",
      "bi.reconTitle": "Rekonsiliasi Finansial & Quality Gates",
      "bi.colCheck": "Nama Pemeriksaan",
      "bi.colStage": "Tahap Gate",
      "bi.colStatus": "Status",
      "bi.colDetails": "Detail Audit",
      "copilot.title": "Analis AI NL-to-SQL Terintegrasi Layer Gold",
      "copilot.subtitle":
        "Ajukan pertanyaan bisnis dengan bahasa alami. SQL read-only tervalidasi AST dijalankan pada kontrak Gold dengan grafik SVG otomatis.",
      "copilot.askBtn": "Analisis Gold",
      "copilot.placeholder": "Tanyakan tentang pendapatan kanal, kategori, ROAS, atau stockout...",
      "copilot.chartLabel": "Visualisasi Otomatis",
      "copilot.tableLabel": "Baris Hasil (Klik header untuk urutkan)",
      "copilot.sqlToggle": "Lihat SQL Read-Only & Provenans Tabel",
      "modal.title": "Hubungkan & Buka Eksekusi Databricks",
      "modal.tabSso": "Portal SSO / Workspace",
      "modal.tabPasscode": "Passcode Demo",
      "modal.tabCredentials": "Workspace Kustom (Host + PAT)",
      "modal.ssoDesc":
        "Workspace enterprise Databricks mengautentikasi pengguna melalui SSO. Buka workspace atau inspeksi Lakeflow Job #1033864740434224 langsung di Databricks.",
      "modal.openWorkspace": "Buka Login Workspace Databricks ↗",
      "modal.openJob": "Buka Job Pipeline Lakeflow ↗",
      "modal.passcodeDesc":
        "Masukkan passcode demo publik untuk membuka eksekusi HMAC sisi server ke workspace Databricks. Token hanya disimpan di sessionStorage tab ini.",
      "modal.passcodeLabel": "Passcode Demo",
      "modal.unlockBtn": "Buka Cloud Live",
      "modal.disconnectBtn": "Putuskan Sesi",
      "modal.credsDesc":
        "Hubungkan workspace Databricks Anda sendiri menggunakan Personal Access Token (BYOK). Kredensial diverifikasi via SCIM /Me dan hanya disimpan di sessionStorage.",
      "modal.hostLabel": "URL Host Workspace",
      "modal.tokenLabel": "Personal Access Token (PAT)",
      "modal.jobLabel": "Job ID (Opsional)",
      "modal.whLabel": "SQL Warehouse ID (Opsional)",
      "modal.connectBtn": "Verifikasi & Hubungkan Workspace",
      "common.copy": "Salin",
      "common.copied": "Disalin",
    },
  };

  const VERIFIED_RUN_SNAPSHOT = {
    run_id: 647116123722071,
    job_id: 1033864740434224,
    overall_status: "SUCCESS",
    start_time: 1763420000000,
    run_duration_ms: 551081,
    run_page_url:
      "https://dbc-118afc22-e599.cloud.databricks.com/?o=7474648823106559#job/1033864740434224/run/647116123722071",
    trigger: "MANUAL",
    tasks: [
      { task_key: "setup_schemas", status: "SUCCESS", execution_duration_ms: 38000, state_message: "Unity Catalog & 25 Delta tables initialized" },
      { task_key: "load_bronze", status: "SUCCESS", execution_duration_ms: 46000, state_message: "158,770 raw records ingested with SHA-256" },
      { task_key: "build_silver", status: "SUCCESS", execution_duration_ms: 91000, state_message: "135,805 clean rows · 1 quarantined reject" },
      { task_key: "silver_quality_gate", status: "SUCCESS", execution_duration_ms: 43000, state_message: "4/4 Silver checks passed" },
      { task_key: "build_gold", status: "SUCCESS", execution_duration_ms: 49000, state_message: "5 Gold analytical marts merged" },
      { task_key: "validate_gold_and_reconciliation", status: "SUCCESS", execution_duration_ms: 34000, state_message: "5/5 Gold checks · $0.00 drift" },
    ],
  };

  const VERIFIED_METRICS_SNAPSHOT = {
    source: "verified_snapshot",
    summary: {
      days: 90,
      total_orders: 10000,
      gross_revenue: 15102816.79,
      net_revenue: 13561301.58,
      average_order_value: 1509.79,
      refund_rate: 0.2269,
      repeat_customer_rate: 0.7548,
      stockout_rate: 0.0001,
      bronze_raw_records: 158770,
      silver_clean_records: 135805,
      silver_rejected_records: 1,
      delta_tables: 25,
      benchmark_passed: "25/25",
      reconciliation_diff: 0.0,
    },
    channels: [
      { sales_channel: "WEB", orders: 2507, net_revenue: 3473000.22, refunded: 413887.11 },
      { sales_channel: "STORE", orders: 2517, net_revenue: 3386261.46, refunded: 363409.34 },
      { sales_channel: "MOBILE_APP", orders: 2494, net_revenue: 3375258.14, refunded: 377163.93 },
      { sales_channel: "MARKETPLACE", orders: 2482, net_revenue: 3326781.76, refunded: 394779.83 },
    ],
    daily_trend: [
      { metric_date: "2026-09-13", total_orders: 111, net_revenue: 149527.46 },
      { metric_date: "2026-09-14", total_orders: 117, net_revenue: 144361.5 },
      { metric_date: "2026-09-15", total_orders: 130, net_revenue: 193374.68 },
      { metric_date: "2026-09-16", total_orders: 103, net_revenue: 133964.58 },
      { metric_date: "2026-09-17", total_orders: 96, net_revenue: 131195.93 },
      { metric_date: "2026-09-18", total_orders: 106, net_revenue: 145606.82 },
      { metric_date: "2026-09-19", total_orders: 103, net_revenue: 124333.06 },
    ],
    quality_checks: [
      { check_name: "silver_orders_row_count", check_stage: "silver_gate", passed: true, details: { order_count: 10000 } },
      { check_name: "silver_no_negative_qty", check_stage: "silver_gate", passed: true, details: { negative_quantity_rows: 0, quarantined: 1 } },
      { check_name: "silver_orders_unique_pk", check_stage: "silver_gate", passed: true, details: { duplicates: 0, tables_audited: 15 } },
      { check_name: "silver_referential_integrity", check_stage: "silver_gate", passed: true, details: { orphan_items: 0, orphan_payments: 0, orphan_refunds: 0 } },
      { check_name: "gold_unique_pks", check_stage: "gold_validation", passed: true, details: { tables_audited: 5, duplicates: 0 } },
      { check_name: "gold_net_revenue_reconciliation", check_stage: "gold_validation", passed: true, details: { order_360: 13561301.58, customer_daily: 13561301.58, diff: 0.0 } },
      { check_name: "gold_refund_reconciliation", check_stage: "gold_validation", passed: true, details: { silver_refunds: 1549240.21, gold_refunds: 1549240.21, diff: 0.0 } },
      { check_name: "gold_kpi_rate_bounds", check_stage: "gold_validation", passed: true, details: { bounds: "[0.0, 1.0]", violations: 0 } },
      { check_name: "gold_non_null_grains", check_stage: "gold_validation", passed: true, details: { null_grain_rows: 0 } },
    ],
  };

  const XRAY_STAGES = [
    {
      id: "raw_volume",
      index: "00",
      pillClass: "",
      location: "/Volumes/retail_analytics/bronze/raw_data/",
      name: { en: "Raw UC Volume", id: "Volume Mentah UC" },
      summary: { en: "19 raw JSON & CSV files", id: "19 berkas JSON & CSV mentah" },
      heading: { en: "Immutable Landing Zone (Unity Catalog Volume)", id: "Zona Pendaratan Imutabel (Unity Catalog Volume)" },
      analogy: {
        business: {
          en: "Like a locked mailroom receiving every POS receipt, webhook, and CSV unmodified—so finance can always inspect the exact original evidence.",
          id: "Ibarat ruang arsip tersegel yang menerima semua struk kasir, webhook, dan CSV apa adanya agar tim audit selalu punya bukti asli.",
        },
        engineer: {
          en: "Raw multi-format JSON/CSV payloads arrive across operational/, events/, inventory/, and reference/ with mixed timezones (+07:00 & Z), duplicate webhooks, and unvalidated line quantities.",
          id: "Payload JSON/CSV mendarat di folder operational/, events/, inventory/, dan reference/ lengkap dengan campuran zona waktu (+07:00 & Z), webhook ganda, dan kuantitas tidak valid.",
        },
      },
      contracts: ["Unity Catalog Managed Volume", "Zero Schema Mutation", "JSON + CSV Multi-Format", "19 Source Files"],
      tables: ["operational/orders.json", "operational/order_items.json", "events/payment_events.json", "operational/order_promotions.json"],
    },
    {
      id: "bronze",
      index: "01",
      pillClass: "pill-bronze",
      location: "retail_analytics.bronze.raw_records",
      name: { en: "Bronze Raw Delta", id: "Bronze Delta Mentah" },
      summary: { en: "158,770 rows · SHA-256", id: "158.770 baris · SHA-256" },
      heading: { en: "Append-Only Raw Ledger & Checksum Audit", id: "Buku Besar Append-Only & Audit Checksum" },
      analogy: {
        business: {
          en: "Every single raw transaction is stamped with a tamper-evident digital fingerprint (SHA-256) and run ID, guaranteeing zero lost events and full lineage.",
          id: "Setiap transaksi mentah dicap sidik jari digital SHA-256 dan ID eksekusi sehingga nol data hilang dan seluruh riwayat dapat dilacak.",
        },
        engineer: {
          en: "bronze_ingestion.py computes streaming SHA-256 checksums into ops.ingested_files, extracts natural source_row_id keys, and appends raw JSON payloads into bronze.raw_records USING DELTA.",
          id: "bronze_ingestion.py menghitung checksum SHA-256 ke ops.ingested_files, mengekstrak source_row_id, dan menyimpan payload mentah ke bronze.raw_records USING DELTA.",
        },
      },
      contracts: ["USING DELTA", "SHA-256 File Lineage", "pipeline_run_id Partitioning", "Append-Only Replayable"],
      tables: ["bronze.raw_records", "ops.ingested_files", "ops.pipeline_runs"],
    },
    {
      id: "silver",
      index: "02",
      pillClass: "pill-silver",
      location: "retail_analytics.silver.* + rejected_records",
      name: { en: "Silver + Rejects", id: "Silver + Karantina" },
      summary: { en: "135,805 clean · 1 rejected", id: "135.805 bersih · 1 ditolak" },
      heading: { en: "Cleansed, Deduplicated & Quarantined Entities", id: "Entitas Terbersihkan, Terdeduplikasi & Terkarantina" },
      analogy: {
        business: {
          en: "Bad rows (like negative item quantities) are isolated into a quarantine vault instead of silently corrupting revenue, while duplicate payment webhooks are merged once.",
          id: "Baris rusak (seperti kuantitas negatif) dipisahkan ke brankas karantina agar tidak merusak angka pendapatan, sementara webhook pembayaran ganda digabung menjadi satu.",
        },
        engineer: {
          en: "silver_transformation.py quarantines quantity <= 0 into silver.rejected_records, deduplicates orders/events via ROW_NUMBER() windowing, and normalizes all timestamps to UTC TIMESTAMP.",
          id: "silver_transformation.py mengarantina quantity <= 0 ke silver.rejected_records, mendepuplikasi order/event dengan ROW_NUMBER(), dan menormalisasi seluruh waktu ke UTC TIMESTAMP.",
        },
      },
      contracts: ["NOT NULL Typed Delta", "Deterministic ROW_NUMBER()", "UTC Timestamp Norm", "Quarantine Dead-Letter"],
      tables: ["silver.orders", "silver.order_items", "silver.rejected_records", "silver.payments", "silver.order_promotions"],
    },
    {
      id: "gold",
      index: "03",
      pillClass: "pill-gold",
      location: "retail_analytics.gold.order_360",
      name: { en: "Gold Order 360", id: "Gold Order 360" },
      summary: { en: "10,000 orders · $0.00 drift", id: "10.000 order · selisih $0,00" },
      heading: { en: "Pre-Aggregated Grain-Safe Analytical Contract", id: "Kontrak Analitik Teragregasi Tanpa Duplikasi Fakta" },
      analogy: {
        business: {
          en: "Executive-ready single source of truth: every order shows exact gross value, promo count, captured payment, and net revenue verified to match finance ledgers.",
          id: "Satu sumber kebenaran siap-eksekutif: tiap order menampilkan nilai kotor, jumlah promo, pembayaran tertangkap, dan pendapatan bersih yang cocok 100% dengan laporan keuangan.",
        },
        engineer: {
          en: "gold_transformation.py pre-aggregates items, payments, refunds, returns, and order_promotions in separate CTEs before LEFT JOIN to avoid fact multiplication, then upserts via Delta MERGE INTO.",
          id: "gold_transformation.py melakukan pra-agregasi item, pembayaran, refund, retur, dan promo pada CTE terpisah sebelum LEFT JOIN untuk mencegah fact multiplication, lalu melakukan MERGE INTO Delta.",
        },
      },
      contracts: ["Zero Fact Multiplication", "Idempotent Delta MERGE", "DECIMAL(14,2) Precision", "0.00 Parity Reconciled"],
      tables: ["gold.order_360", "gold.customer_daily", "gold.product_daily", "gold.channel_campaign_daily", "gold.executive_kpis_daily"],
    },
  ];

  const XRAY_ORDERS = [
    {
      id: "ORD-000007",
      label: "ORD-000007 · Qty -2 Reject + Promos",
      verdict: { en: "1 ROW QUARANTINED · +07:00 FIXED", id: "1 BARIS DIKARANTINA · +07:00 DINORMALISASI" },
      isQuarantine: true,
      stages: {
        raw_volume: {
          file: "data/operational/order_items.json + payment_events.json",
          note: {
            en: "Raw feed contains 4 line items (one invalid quantity: -2), a +07:00 payment timestamp, and 2 applied promotions.",
            id: "Feed mentah berisi 4 item (satu kuantitas tidak valid: -2), timestamp pembayaran +07:00, dan 2 promosi.",
          },
          code: `{
  "order": {
    "order_id": "ORD-000007",
    "customer_id": "CUST-00632",
    "sales_channel": "STORE",
    "store_id": "STORE-03",
    "ordered_at_utc": "2026-07-18T05:24:00Z"
  },
  "anomalous_item": {
    "order_item_id": "ITEM-000007-01",
    "product_id": "PROD-00056",
    "quantity": -2,
    "unit_price": 187.58,
    "item_discount_amount": 5.0
  },
  "payment_event": {
    "event_id": "EVT-00000033",
    "event_type": "PAYMENT_CAPTURED",
    "occurred_at_utc": "2026-07-18T13:24:00+07:00",
    "payload": { "payment_id": "PAY-ORD-000007", "amount": 2482.04 }
  },
  "order_promotions": ["PROMO-003 ($5.00)", "PROMO-008 ($15.00)"]
}`,
        },
        bronze: {
          file: "retail_analytics.bronze.raw_records",
          note: {
            en: "All raw JSON payloads landed immutably with source_row_id and SHA-256 checksum recorded in ops.ingested_files.",
            id: "Seluruh payload JSON mentah masuk secara imutabel bersama source_row_id dan checksum SHA-256 di ops.ingested_files.",
          },
          code: `SELECT pipeline_run_id, source_category, file_name, source_row_id, payload
FROM retail_analytics.bronze.raw_records
WHERE source_row_id IN ('ORDER-ROW-0000007', 'ITEM-ROW-0000007-01', 'EVT-00000033');

-- Result (preserved verbatim):
-- | operational | order_items.json    | ITEM-ROW-0000007-01 | {"quantity": -2, ...}   |
-- | operational | orders.json         | ORDER-ROW-0000007   | {"sales_channel":"STORE"}|
-- | events      | payment_events.json | EVT-00000033        | {"amount": 2482.04, ...} |`,
        },
        silver: {
          file: "silver.rejected_records + silver.order_items + silver.payments",
          note: {
            en: "ITEM-000007-01 (quantity: -2) is quarantined to silver.rejected_records. Remaining 3 clean items total 9 units; +07:00 normalizes to 06:24:00Z.",
            id: "ITEM-000007-01 (quantity: -2) dikarantina ke silver.rejected_records. 3 item bersih tersisa berjumlah 9 unit; +07:00 dinormalisasi menjadi 06:24:00Z.",
          },
          code: `-- 1) Quarantined to retail_analytics.silver.rejected_records:
{
  "source_table": "order_items",
  "record_identifier": "ITEM-000007-01",
  "reject_reason": "INVALID_QUANTITY_NEGATIVE_OR_ZERO",
  "payload": { "order_id": "ORD-000007", "quantity": -2, "unit_price": 187.58 }
}

-- 2) Clean Silver rows accepted:
-- silver.order_items: 3 rows (ITEM-02 qty=3 @298.58, ITEM-03 qty=2 @61.95, ITEM-04 qty=4 @371.85)
-- silver.payments:    PAY-ORD-000007 | captured_amount: 2482.04 | occurred_at_utc: 2026-07-18T06:24:00Z
-- silver.order_promotions: 2 rows (PROMO-003, PROMO-008)`,
        },
        gold: {
          file: "retail_analytics.gold.order_360",
          note: {
            en: "Single grain-safe row in gold.order_360: rejected negative item excluded, dynamic promotion_count = 2, payment_status = CAPTURED.",
            id: "Satu baris akurat di gold.order_360: item negatif tidak ikut terhitung, promotion_count = 2 dinamis, payment_status = CAPTURED.",
          },
          code: `{
  "order_id": "ORD-000007",
  "customer_id": "CUST-00632",
  "order_date": "2026-07-18",
  "sales_channel": "STORE",
  "store_id": "STORE-03",
  "gross_merchandise_value": 2507.04,
  "discount_amount": 5.00,
  "shipping_revenue": 0.00,
  "captured_payment_amount": 2482.04,
  "refunded_amount": 0.00,
  "net_revenue": 2502.04,
  "item_count": 3,
  "unit_quantity": 9,
  "order_status": "FULFILLED",
  "payment_status": "CAPTURED",
  "return_status": "NONE",
  "promotion_count": 2,
  "first_order_flag": true
}`,
        },
      },
    },
    {
      id: "ORD-001662",
      label: "ORD-001662 · Dup Payment Webhook + Refund",
      verdict: { en: "WEBHOOK DEDUPED · $3,734.64 SAFE", id: "WEBHOOK DIDEDUPLIKASI · $3.734,64 AMAN" },
      isQuarantine: false,
      stages: {
        raw_volume: {
          file: "data/events/payment_events.json + refund_events.json + return_events.json",
          note: {
            en: "Gateway emitted duplicate PAYMENT_CAPTURED webhook EVT-00010230 ($3,734.64 twice) alongside partial refund and return lifecycle events.",
            id: "Gateway mengirim ulang webhook PAYMENT_CAPTURED EVT-00010230 ($3.734,64 dua kali) disertai event refund parsial dan retur.",
          },
          code: `{
  "order_id": "ORD-001662",
  "sales_channel": "MARKETPLACE",
  "duplicate_webhooks": [
    { "event_id": "EVT-00010230", "event_type": "PAYMENT_CAPTURED", "occurred_at_utc": "2026-09-14T02:32:00+07:00", "amount": 3734.64 },
    { "event_id": "EVT-00010230", "event_type": "PAYMENT_CAPTURED", "occurred_at_utc": "2026-09-14T02:32:00+07:00", "amount": 3734.64 }
  ],
  "refund_event": { "refund_id": "REF-ORD-001662-01", "event_type": "REFUND_COMPLETED", "amount": 1867.32 },
  "return_events": ["RETURN_REQUESTED", "RETURN_RECEIVED"],
  "web_purchase": { "campaign_id": "CMP-04", "session_id": "SESSION-ORD-001662" }
}`,
        },
        bronze: {
          file: "retail_analytics.bronze.raw_records",
          note: {
            en: "Both duplicate webhook deliveries are preserved in Bronze for operational replayability and webhook auditing.",
            id: "Kedua kiriman webhook duplikat tetap disimpan di Bronze untuk jejak audit operasional.",
          },
          code: `-- Bronze preserves both EVT-00010230 rows without dropping raw audit history:
-- row_id: EVT-00010230 | file: payment_events.json | amount: 3734.64
-- row_id: EVT-00010230 | file: payment_events.json | amount: 3734.64
-- row_id: EVT-00010232 | file: refund_events.json  | REFUND_COMPLETED 1867.32
-- row_id: EVT-00010234 | file: return_events.json  | RETURN_RECEIVED`,
        },
        silver: {
          file: "silver.payments + silver.refunds + silver.returns",
          note: {
            en: "Window deduplication on event_id collapses duplicate EVT-00010230 to 1 payment ($3,734.64, preventing a $7,469.28 overcount).",
            id: "Deduplikasi window pada event_id menggabungkan EVT-00010230 ganda menjadi 1 pembayaran ($3.734,64, mencegah penggandaan jadi $7.469,28).",
          },
          code: `-- silver.payments (ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY ingested_at_utc DESC)):
PAY-ORD-001662 | captured_amount: 3734.64 | occurred_at_utc: 2026-09-13T19:32:00Z

-- silver.refunds (prioritizes REFUND_COMPLETED):
REF-ORD-001662-01 | refund_amount: 1867.32 | refund_status: REFUND_COMPLETED

-- silver.returns (latest status):
RETURN-ORD-001662 | return_status: RETURN_RECEIVED`,
        },
        gold: {
          file: "retail_analytics.gold.order_360 + channel_campaign_daily",
          note: {
            en: "Gold calculates exact net_revenue ($1,867.32), surfaces dynamic return_status = RETURN_RECEIVED, and attributes order to CMP-04.",
            id: "Gold menghitung net_revenue tepat ($1.867,32), return_status dinamis RETURN_RECEIVED, serta mengatribusikan order ke CMP-04.",
          },
          code: `{
  "order_id": "ORD-001662",
  "customer_id": "CUST-01444",
  "order_date": "2026-09-13",
  "sales_channel": "MARKETPLACE",
  "gross_merchandise_value": 3744.64,
  "discount_amount": 10.00,
  "captured_payment_amount": 3734.64,
  "refunded_amount": 1867.32,
  "net_revenue": 1867.32,
  "payment_status": "CAPTURED",
  "return_status": "RETURN_RECEIVED",
  "attributed_campaign": "CMP-04"
}`,
        },
      },
    },
    {
      id: "ORD-000001",
      label: "ORD-000001 · Dup Order Row + Promo + CMP-09",
      verdict: { en: "ORDER DEDUPED · CMP-09 ATTRIBUTED", id: "ORDER DIDEDUPLIKASI · ATRIBUSI CMP-09" },
      isQuarantine: false,
      stages: {
        raw_volume: {
          file: "data/operational/orders.json + web_events.json",
          note: {
            en: "orders.json contains 2 records for ORD-000001 (ORDER-ROW-0000001 and ORDER-ROW-DUPLICATE-0001) plus MOBILE_APP campaign CMP-09.",
            id: "orders.json berisi 2 baris untuk ORD-000001 (ORDER-ROW-0000001 dan ORDER-ROW-DUPLICATE-0001) serta kampanye MOBILE_APP CMP-09.",
          },
          code: `[
  { "source_row_id": "ORDER-ROW-0000001", "order_id": "ORD-000001", "sales_channel": "MOBILE_APP", "shipping_revenue": 12.0, "updated_at_utc": "2026-08-20T23:16:00Z" },
  { "source_row_id": "ORDER-ROW-DUPLICATE-0001", "order_id": "ORD-000001", "sales_channel": "MOBILE_APP", "shipping_revenue": 12.0, "updated_at_utc": "2026-08-20T23:16:00Z" }
]
// Promo: PROMO-006 ($5.00) · Web PURCHASE: campaign_id = "CMP-09"`,
        },
        bronze: {
          file: "retail_analytics.bronze.raw_records",
          note: {
            en: "10,001 order rows (including ORDER-ROW-DUPLICATE-0001) are faithfully logged in Bronze with zero mutation.",
            id: "10.001 baris order (termasuk ORDER-ROW-DUPLICATE-0001) dicatat utuh di Bronze tanpa modifikasi.",
          },
          code: `-- Bronze captures both rows with their exact source_row_id:
-- ORDER-ROW-0000001        | ORD-000001 | 2026-08-20T23:16:00Z
-- ORDER-ROW-DUPLICATE-0001 | ORD-000001 | 2026-08-20T23:16:00Z`,
        },
        silver: {
          file: "retail_analytics.silver.orders",
          note: {
            en: "Deterministic ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY updated_at_utc DESC) keeps exactly 10,000 unique orders.",
            id: "ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY updated_at_utc DESC) menyisakan tepat 10.000 order unik.",
          },
          code: `WITH ranked_orders AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY updated_at_utc DESC) AS rn
  FROM bronze_orders
)
SELECT order_id, customer_id, sales_channel, shipping_revenue
FROM ranked_orders WHERE rn = 1;
-- Keeps 1 row for ORD-000001 (CUST-01757, MOBILE_APP, shipping: 12.00)`,
        },
        gold: {
          file: "retail_analytics.gold.order_360",
          note: {
            en: "Single row in gold.order_360 with GMV $1,118.24 + shipping $12.00 = $1,130.24 net revenue and CMP-09 ROAS attribution.",
            id: "Satu baris di gold.order_360 dengan GMV $1.118,24 + ongkir $12,00 = pendapatan bersih $1.130,24 dan atribusi ROAS CMP-09.",
          },
          code: `{
  "order_id": "ORD-000001",
  "customer_id": "CUST-01757",
  "order_date": "2026-08-20",
  "sales_channel": "MOBILE_APP",
  "gross_merchandise_value": 1118.24,
  "shipping_revenue": 12.00,
  "captured_payment_amount": 1125.24,
  "net_revenue": 1130.24,
  "item_count": 2,
  "unit_quantity": 4,
  "promotion_count": 1,
  "attributed_campaign": "CMP-09"
}`,
        },
      },
    },
  ];

  const STACKS = {
    databricks: {
      id: "databricks",
      subtitle: {
        en: "Databricks Lakeflow Serverless Job (resources/retail_pipeline_job.yml · 6 tasks)",
        id: "Databricks Lakeflow Serverless Job (resources/retail_pipeline_job.yml · 6 task)",
      },
      tasks: [
        {
          task_key: "setup_schemas",
          layer: "OPS / UC",
          pillClass: "pill-ops",
          defaultDurationMs: 38000,
          shortLabel: { en: "Unity Catalog & Delta DDLs", id: "Unity Catalog & DDL Delta" },
          desc: {
            en: "Initializes retail_analytics catalog, bronze/silver/gold/ops schemas, raw_data Volume, and 25 Delta tables.",
            id: "Menginisialisasi katalog retail_analytics, skema bronze/silver/gold/ops, Volume raw_data, dan 25 tabel Delta.",
          },
          recruiterPoints: {
            en: [
              "Demonstrates Infrastructure-as-Code governance via Databricks Asset Bundles (DABs) and Unity Catalog.",
              "Enforces typed Delta Lake contracts with explicit PRIMARY KEY constraints across all 4 schemas.",
            ],
            id: [
              "Menunjukkan tata kelola Infrastructure-as-Code melalui Databricks Asset Bundles (DABs) dan Unity Catalog.",
              "Menerapkan kontrak tabel Delta Lake bertipe eksplisit beserta constraint PRIMARY KEY di seluruh skema.",
            ],
          },
          businessImpact: {
            en: "Provides centralized lineage, access governance, and reproducible dev/prod environment promotion.",
            id: "Menyediakan tata kelola akses terpusat, lineage otomatis, dan promosi lingkungan dev/prod yang konsisten.",
          },
          engineerNotes: {
            en: "Executes setup_unity_catalog.py on Serverless Env v3, templating ${catalog_name} across create_delta_tables.sql with CREATE SCHEMA/TABLE IF NOT EXISTS.",
            id: "Menjalankan setup_unity_catalog.py di Serverless Env v3, mengganti ${catalog_name} pada create_delta_tables.sql secara idempoten.",
          },
          tags: ["Unity Catalog", "DABs", "25 Delta Tables", "Serverless v3"],
          filePath: "databricks/schemas/setup_unity_catalog.py",
          language: "python",
          code: `def setup_unity_catalog(
    catalog: str = "retail_analytics",
    spark: Any = None,
    create_tables: bool = True,
) -> None:
    ddls = [
        f"CREATE CATALOG IF NOT EXISTS {catalog}",
        f"USE CATALOG {catalog}",
        f"CREATE SCHEMA IF NOT EXISTS {catalog}.bronze COMMENT 'Bronze Layer: Raw ingested data'",
        f"CREATE SCHEMA IF NOT EXISTS {catalog}.silver COMMENT 'Silver Layer: Cleaned and normalized tables'",
        f"CREATE SCHEMA IF NOT EXISTS {catalog}.gold COMMENT 'Gold Layer: Aggregated business metrics'",
        f"CREATE SCHEMA IF NOT EXISTS {catalog}.ops COMMENT 'Operations Layer: Lifecycle and quality checks'",
        f"CREATE VOLUME IF NOT EXISTS {catalog}.bronze.raw_data COMMENT 'Volume storing landed JSON/CSV files'",
    ]
    for ddl in ddls:
        if spark is not None:
            spark.sql(ddl)`,
        },
        {
          task_key: "load_bronze",
          layer: "BRONZE",
          pillClass: "pill-bronze",
          defaultDurationMs: 46000,
          shortLabel: { en: "Volume Ingestion + SHA-256", id: "Ingesti Volume + SHA-256" },
          desc: {
            en: "Discovers all 19 JSON/CSV files from /Volumes/retail_analytics/bronze/raw_data/, computes SHA-256 checksums, and ingests 158,770 raw rows.",
            id: "Menemukan 19 berkas JSON/CSV dari Volume UC, menghitung checksum SHA-256, dan memuat 158.770 baris mentah.",
          },
          recruiterPoints: {
            en: [
              "Preserves 100% raw payload fidelity so historical bugs can be replayed without re-scraping sources.",
              "Tracks file-level SHA-256 checksums and row counts in ops.ingested_files for compliance audits.",
            ],
            id: [
              "Menjaga keutuhan payload mentah 100% agar pemrosesan ulang historis dapat dilakukan tanpa menarik ulang data sumber.",
              "Mencatat checksum SHA-256 dan jumlah baris per berkas di ops.ingested_files untuk jejak audit.",
            ],
          },
          businessImpact: {
            en: "Eliminates silent data drops at ingestion by logging every landed file and record count before transformation.",
            id: "Mencegah hilangnya data saat ingesti dengan mencatat setiap berkas dan jumlah baris sebelum transformasi.",
          },
          engineerNotes: {
            en: "Resolves UC Volume -> data/raw -> data/ dynamically, extracts natural source_row_id, writes Delta append to bronze.raw_records, and upserts ops.pipeline_runs via MERGE INTO.",
            id: "Meresolusi Volume UC -> data/raw -> data/ secara dinamis, mengekstrak source_row_id, menulis ke bronze.raw_records, dan memperbarui ops.pipeline_runs via MERGE INTO.",
          },
          tags: ["PySpark", "SHA-256", "158,770 Rows", "ops.ingested_files"],
          filePath: "databricks/pipelines/bronze_ingestion.py",
          language: "python",
          code: `for category, file_path in discovered:
    file_name = file_path.name
    checksum = compute_sha256(file_path)
    id_col = KNOWN_ID_COLS.get(file_name)
    ...
raw_df.write.format("delta").mode("append").saveAsTable(
    f"{catalog}.bronze.raw_records"
)
spark.sql(f"""
    MERGE INTO {catalog}.ops.pipeline_runs AS target
    USING (SELECT '{run_id}' AS run_id, {total_records} AS records_read) AS source
    ON target.run_id = source.run_id
    WHEN MATCHED THEN UPDATE SET target.records_read = source.records_read, target.current_stage = 'bronze'
    WHEN NOT MATCHED THEN INSERT (run_id, started_at_utc, status, current_stage, records_read)
    VALUES (source.run_id, current_timestamp(), 'RUNNING', 'bronze', source.records_read)
""")`,
        },
        {
          task_key: "build_silver",
          layer: "SILVER",
          pillClass: "pill-silver",
          defaultDurationMs: 91000,
          shortLabel: { en: "Cleanse, Dedup & Quarantine", id: "Bersihkan, Dedup & Karantina" },
          desc: {
            en: "Quarantines negative quantities (qty <= 0) into silver.rejected_records, deduplicates orders/events, normalizes +07:00 timestamps to UTC, and populates 15 clean Silver Delta tables.",
            id: "Mengarantina kuantitas <= 0 ke silver.rejected_records, mendepuplikasi order/event, menormalisasi waktu ke UTC, dan mengisi 15 tabel Silver bersih.",
          },
          recruiterPoints: {
            en: [
              "Implements an explicit dead-letter quarantine table (silver.rejected_records) instead of silently filtering bad records.",
              "Solves real-world duplicate payment webhooks and out-of-order updates deterministically via PySpark Window functions.",
            ],
            id: [
              "Menerapkan tabel karantina eksplisit (silver.rejected_records) alih-alih membuang baris anomali secara diam-diam.",
              "Menyelesaikan duplikasi webhook pembayaran dan pembaruan tak berurut secara deterministik menggunakan Window PySpark.",
            ],
          },
          businessImpact: {
            en: "Protects financial reporting from double-counted duplicate webhooks and corrupted negative line-item quantities.",
            id: "Melindungi laporan keuangan dari penghitungan ganda webhook dan item berkuantitas negatif.",
          },
          engineerNotes: {
            en: "Uses F.get_json_object + F.to_timestamp to normalize mixed timezone strings, ROW_NUMBER() windowing per primary key, and idempotent per-run_id Delta replacement.",
            id: "Menggunakan F.get_json_object + F.to_timestamp untuk normalisasi zona waktu, window ROW_NUMBER(), serta penulisan Delta idempoten per run_id.",
          },
          tags: ["Quarantine Pattern", "Window Dedup", "UTC Normalization", "135,805 Rows"],
          filePath: "databricks/pipelines/silver_transformation.py",
          language: "python",
          code: `rejected_items_df = (
    order_items_raw.filter(
        F.coalesce(F.get_json_object("payload", "$.quantity").cast("int"), F.lit(0)) <= 0
    ).select(
        F.lit(run_id).alias("pipeline_run_id"),
        F.lit("order_items").alias("source_table"),
        F.get_json_object("payload", "$.order_item_id").alias("record_identifier"),
        F.lit("INVALID_QUANTITY_NEGATIVE_OR_ZERO").alias("reject_reason"),
        F.col("payload").cast("string").alias("payload"),
        F.current_timestamp().alias("rejected_at_utc"),
    )
)
window_order = Window.partitionBy("order_id").orderBy(F.col("updated_at_utc").desc())`,
        },
        {
          task_key: "silver_quality_gate",
          layer: "GATE",
          pillClass: "pill-ops",
          defaultDurationMs: 43000,
          shortLabel: { en: "Silver Circuit Breaker", id: "Circuit Breaker Silver" },
          desc: {
            en: "Fail-fast quality gate auditing positive order count, zero negative quantities in clean items, unique PKs across 15 Silver tables, and zero orphan children.",
            id: "Quality gate fail-fast yang memverifikasi jumlah order, nol kuantitas negatif, keunikan PK di 15 tabel Silver, dan integritas referensial.",
          },
          recruiterPoints: {
            en: [
              "Circuit-breaker pattern: raises ValueError and halts downstream Gold builds if any Silver contract invariant fails.",
              "Persists structured JSON audit diagnostics into ops.quality_checks for every pipeline execution.",
            ],
            id: [
              "Pola circuit-breaker: membangkitkan ValueError dan memblokir pembangunan Gold bila kontrak Silver dilanggar.",
              "Menyimpan hasil audit JSON terstruktur ke ops.quality_checks pada setiap eksekusi.",
            ],
          },
          businessImpact: {
            en: "Prevents corrupted upstream feeds from ever reaching executive dashboards or customer-facing BI metrics.",
            id: "Mencegah data bermasalah mencapai dashboard eksekutif atau metrik BI.",
          },
          engineerNotes: {
            en: "Invoked with --stage silver. Evaluates silver_orders_exist, no_negative_qty_in_clean, unique_keys (15 tables), and referential_integrity (order_items, payments, refunds, returns).",
            id: "Dijalankan dengan --stage silver untuk memeriksa silver_orders_exist, no_negative_qty_in_clean, unique_keys (15 tabel), dan referential_integrity.",
          },
          tags: ["Fail-Fast Gate", "Referential Integrity", "PK Uniqueness", "ops.quality_checks"],
          filePath: "databricks/pipelines/quality_checks.py",
          language: "python",
          code: `neg_qty_count = spark.sql(
    f"SELECT COUNT(*) FROM {catalog}.silver.order_items "
    f"WHERE pipeline_run_id = '{run_id}' AND quantity <= 0"
).collect()[0][0]
c2_passed = (neg_qty_count == 0)
record_quality_check(
    spark, catalog, run_id, "no_negative_qty_in_clean", "silver_gate",
    c2_passed, {"negative_quantity_rows": int(neg_qty_count)}
)
if not all_passed:
    raise ValueError(f"Silver Quality Gate FAILED for run '{run_id}'.")`,
        },
        {
          task_key: "build_gold",
          layer: "GOLD",
          pillClass: "pill-gold",
          defaultDurationMs: 49000,
          shortLabel: { en: "5 Grain-Safe Gold Marts", id: "5 Mart Gold Tanpa Duplikasi" },
          desc: {
            en: "Builds gold.order_360, customer_daily, product_daily, channel_campaign_daily, and executive_kpis_daily with dynamic SCD2 categories, promo attribution, and zero hardcodes.",
            id: "Membangun 5 tabel Gold dengan kategori temporal SCD2, atribusi promo & kampanye web PURCHASE dinamis, dan tanpa konstanta hardcode.",
          },
          recruiterPoints: {
            en: [
              "Eliminates classic SQL fan-out (fact multiplication) by pre-aggregating each grain in isolated CTEs before joining.",
              "Implements dynamic SCD Type 2 category lookup, web PURCHASE attribution, ROAS, and stockout capture on zero-sale days.",
            ],
            id: [
              "Menghilangkan fan-out SQL (fact multiplication) dengan pra-agregasi tiap grain pada CTE terpisah sebelum join.",
              "Menerapkan lookup kategori temporal SCD2, atribusi PURCHASE, ROAS, dan deteksi stockout pada hari tanpa penjualan.",
            ],
          },
          businessImpact: {
            en: "Delivers accurate omnichannel ROAS, repeat customer behavior, stockout visibility, and order-level margin profitability.",
            id: "Menghadirkan metrik ROAS omnichannel, perilaku pelanggan berulang, visibilitas stockout, dan profitabilitas order yang akurat.",
          },
          engineerNotes: {
            en: "Executes idempotent Delta MERGE INTO on all 5 Gold tables so re-runs safely update existing grains without duplicating rows.",
            id: "Menjalankan Delta MERGE INTO idempoten pada seluruh 5 tabel Gold agar eksekusi ulang memperbarui grain tanpa duplikasi.",
          },
          tags: ["Zero Fact Multiplication", "Delta MERGE", "SCD2 Temporal Join", "Dynamic ROAS"],
          filePath: "databricks/pipelines/gold_transformation.py",
          language: "python",
          code: `MERGE INTO {catalog}.gold.order_360 AS target
USING src_order_360 AS source
ON target.order_id = source.order_id
WHEN MATCHED THEN UPDATE SET
    target.net_revenue = source.net_revenue,
    target.return_status = source.return_status,
    target.promotion_count = source.promotion_count,
    target.first_order_flag = source.first_order_flag
WHEN NOT MATCHED THEN INSERT (order_id, customer_id, order_date, ..., net_revenue, ...)
VALUES (source.order_id, source.customer_id, source.order_date, ..., source.net_revenue, ...)`,
        },
        {
          task_key: "validate_gold_and_reconciliation",
          layer: "RECON",
          pillClass: "pill-ops",
          defaultDurationMs: 34000,
          shortLabel: { en: "Zero-Drift Reconciliation", id: "Rekonsiliasi Zero-Drift" },
          desc: {
            en: "Verifies Gold PK uniqueness, $0.00 net revenue parity across order_360 / customer_daily / executive_kpis_daily, $0.00 refund parity against silver.refunds, and KPI bounds [0, 1].",
            id: "Memvalidasi keunikan PK Gold, paritas pendapatan bersih $0,00 lintas 3 tabel, paritas refund $0,00 vs silver.refunds, dan batas rasio [0, 1].",
          },
          recruiterPoints: {
            en: [
              "Proves financial-grade cross-table reconciliation ($0.00 drift) rather than relying solely on schema checks.",
              "Guards NL-to-SQL AI outputs by verifying every analytical contract grain is non-null and bounded.",
            ],
            id: [
              "Membuktikan rekonsiliasi lintas tabel berstandar finansial (selisih $0,00), bukan sekadar cek skema dasar.",
              "Menjaga kualitas jawaban AI NL-to-SQL dengan memastikan seluruh grain kontrak non-null dan berada pada rentang valid.",
            ],
          },
          businessImpact: {
            en: "Guarantees CFO-level trust: executive KPI totals match customer and order-level drilldowns to the exact cent.",
            id: "Menjamin kepercayaan level eksekutif: total KPI harian persis sama dengan rincian pelanggan dan order hingga ke sen.",
          },
          engineerNotes: {
            en: "Invoked with --stage gold. Checks diff_order_customer < 0.01, diff_order_executive < 0.01, diff_silver_order < 0.01, and rate bounds 0 <= r <= 1.",
            id: "Dijalankan dengan --stage gold untuk memeriksa diff < 0.01 pada pendapatan & refund serta batas laju 0 <= r <= 1.",
          },
          tags: ["$0.00 Drift", "Cross-Table Parity", "KPI Bounds [0,1]", "Audit Ready"],
          filePath: "databricks/pipelines/quality_checks.py",
          language: "python",
          code: `diff_order_cust = round(abs(val_order_rev - val_cust_rev), 2)
diff_order_exec = round(abs(val_order_rev - val_exec_rev), 2)
c2_passed = (diff_order_cust < 0.01) and (diff_order_exec < 0.01)
record_quality_check(
    spark, catalog, run_id, "revenue_reconciliation", "gold_validation",
    c2_passed, {
        "order_360_net_revenue": val_order_rev,
        "customer_daily_net_revenue": val_cust_rev,
        "diff_order_customer": diff_order_cust,
        "diff_order_executive": diff_order_exec,
    }
)`,
        },
      ],
    },
    airflow: {
      id: "airflow",
      subtitle: {
        en: "Apache Airflow + PostgreSQL Local Medallion DAG (dags/dag.py · 7 tasks)",
        id: "DAG Lokal Apache Airflow + PostgreSQL (dags/dag.py · 7 task)",
      },
      tasks: [
        {
          task_key: "validate_raw",
          layer: "PREFLIGHT",
          pillClass: "",
          defaultDurationMs: 1200,
          shortLabel: { en: "Verify Folders & Manifest", id: "Verifikasi Folder & Manifest" },
          desc: {
            en: "Validates operational/events/inventory/reference folders, checks manifest.json SHA-256 hashes if present, and pushes pipeline_run_id via XCom.",
            id: "Memvalidasi folder raw data, memverifikasi hash SHA-256 manifest.json bila ada, dan mengirim pipeline_run_id lewat XCom.",
          },
          recruiterPoints: {
            en: [
              "Detects incomplete deliveries or corrupted landing files before allocating database transactions.",
              "Passes deterministic run_id across downstream Airflow operators via XCom.",
            ],
            id: [
              "Mendeteksi berkas sumber yang tidak lengkap atau rusak sebelum membuka transaksi database.",
              "Mengalirkan run_id deterministik ke seluruh operator hilir via XCom.",
            ],
          },
          businessImpact: {
            en: "Prevents partial or stale file batches from triggering incomplete nightly refreshes.",
            id: "Mencegah pemrosesan parsial saat unggahan data sumber belum lengkap.",
          },
          engineerNotes: {
            en: "Inspects DATA_ROOT dynamically (data/raw fallback to data/) and verifies sha256 digests against manifest.json.",
            id: "Memeriksa DATA_ROOT secara dinamis (data/raw fallback ke data/) dan mencocokkan digest SHA-256 manifest.",
          },
          tags: ["Airflow XCom", "SHA-256 Manifest", "Preflight Check"],
          filePath: "dags/dag.py",
          language: "python",
          code: `def task_validate_raw(**context) -> str:
    run_id = f"run_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    required_folders = ["operational", "events", "inventory", "reference"]
    missing = [f for f in required_folders if not (DATA_ROOT / f).exists()]
    if missing:
        raise AirflowException(f"Folder raw data tidak lengkap: {missing}")
    ti = context.get("ti")
    if ti:
        ti.xcom_push(key="pipeline_run_id", value=run_id)
    return run_id`,
        },
        {
          task_key: "initialize_schema",
          layer: "DDL",
          pillClass: "pill-ops",
          defaultDurationMs: 1800,
          shortLabel: { en: "Apply Postgres Schemas", id: "Terapkan Skema Postgres" },
          desc: {
            en: "Applies ops.sql, bronze.sql, silver.sql, and gold.sql idempotently and registers the RUNNING row in ops.pipeline_runs.",
            id: "Menerapkan ops.sql, bronze.sql, silver.sql, dan gold.sql secara idempoten lalu mencatat baris RUNNING pada ops.pipeline_runs.",
          },
          recruiterPoints: {
            en: [
              "Idempotent DDL bootstrapping enables zero-touch local Docker & CI test environments.",
              "Tracks pipeline lifecycle state from initial RUNNING timestamp through terminal completion.",
            ],
            id: [
              "Bootstrap DDL idempoten memungkinkan setup Docker lokal dan lingkungan uji CI berjalan otomatis.",
              "Melacak status siklus eksekusi sejak RUNNING hingga selesai.",
            ],
          },
          businessImpact: {
            en: "Eliminates manual DBA setup steps and tracks SLA execution times automatically.",
            id: "Menghilangkan langkah setup manual dan memantau durasi eksekusi SLA otomatis.",
          },
          engineerNotes: {
            en: "Uses shared.db.connect('local') pure-Python pg8000 adapter and executes DDL scripts in dependency order.",
            id: "Memakai konektor shared.db.connect('local') berbasis pg8000 dan menjalankan DDL sesuai urutan dependensi.",
          },
          tags: ["PostgreSQL", "Idempotent DDL", "ops.pipeline_runs"],
          filePath: "dags/dag.py",
          language: "python",
          code: `schema_files = [
    PROJECT_ROOT / "database" / "schemas" / "ops.sql",
    PROJECT_ROOT / "database" / "schemas" / "bronze.sql",
    PROJECT_ROOT / "database" / "schemas" / "silver.sql",
    PROJECT_ROOT / "database" / "schemas" / "gold.sql",
]
with connect("local") as conn:
    for sql_file in schema_files:
        conn.execute(sql_file.read_text(encoding="utf-8"))`,
        },
        {
          task_key: "load_bronze",
          layer: "BRONZE",
          pillClass: "pill-bronze",
          defaultDurationMs: 9500,
          shortLabel: { en: "Batch JSONB Ingestion", id: "Ingesti Batch JSONB" },
          desc: {
            en: "Batches 158,770 records (1,000 rows/query) into PostgreSQL bronze.raw_records JSONB and logs file checksums.",
            id: "Memuat 158.770 baris secara batch (1.000 baris/kueri) ke JSONB bronze.raw_records dan mencatat checksum.",
          },
          recruiterPoints: {
            en: [
              "Optimized multi-row batch insertion reduces ~158k round-trips down to ~160 queries.",
              "Exact feature parity with the Databricks PySpark Bronze loader.",
            ],
            id: [
              "Optimasi batch insert multi-baris memangkas ~158 ribu round-trip menjadi ~160 kueri saja.",
              "Memiliki paritas fitur penuh dengan loader Bronze PySpark di Databricks.",
            ],
          },
          businessImpact: {
            en: "Keeps local developer iterations under 15 seconds for full-dataset testing.",
            id: "Menjaga iterasi pengujian lokal dataset penuh tetap cepat di bawah 15 detik.",
          },
          engineerNotes: {
            en: "Streams JSON/JSONL/CSV files, computes SHA-256, and executes parameterized multi-row inserts into bronze.raw_records.",
            id: "Membaca JSON/JSONL/CSV, menghitung SHA-256, dan mengeksekusi insert multi-baris ke bronze.raw_records.",
          },
          tags: ["JSONB", "Batch Insert 1k", "158,770 Rows"],
          filePath: "pipelines/bronze/build_bronze.py",
          language: "python",
          code: `def discover_source_files(data_root: Path) -> list[tuple[str, Path]]:
    target_categories = ["operational", "events", "inventory", "reference"]
    files_to_process: list[tuple[str, Path]] = []
    for category in target_categories:
        cat_dir = data_root / category
        if not cat_dir.exists():
            continue
        for file_path in sorted(cat_dir.rglob("*")):
            if file_path.is_file() and file_path.suffix.lower() in {".json", ".csv", ".jsonl"}:
                files_to_process.append((category, file_path))
    return files_to_process`,
        },
        {
          task_key: "build_silver",
          layer: "SILVER",
          pillClass: "pill-silver",
          defaultDurationMs: 7400,
          shortLabel: { en: "JSONB -> Typed Silver", id: "JSONB -> Silver Bertipe" },
          desc: {
            en: "Quarantines quantity <= 0 into silver.rejected_records and transforms JSONB payloads into 15 typed, deduplicated Postgres Silver tables.",
            id: "Mengarantina quantity <= 0 ke silver.rejected_records dan menormalisasi JSONB menjadi 15 tabel Silver Postgres terdeduplikasi.",
          },
          recruiterPoints: {
            en: [
              "Mirrors Databricks quarantine and window deduplication logic in pure PostgreSQL SQL.",
              "Casts mixed timezone strings to TIMESTAMPTZ consistently.",
            ],
            id: [
              "Mencerminkan logika karantina dan deduplikasi window Databricks dalam SQL PostgreSQL murni.",
              "Mengonversi seluruh stempel waktu ke TIMESTAMPTZ secara konsisten.",
            ],
          },
          businessImpact: {
            en: "Guarantees identical cleansing behavior between local Postgres development and Databricks cloud.",
            id: "Menjamin hasil pembersihan identik antara pengembangan Postgres lokal dan cloud Databricks.",
          },
          engineerNotes: {
            en: "Extracts JSONB operators (->>) with DISTINCT ON / ROW_NUMBER() windowing and records clean_count + reject_count into ops.pipeline_runs.",
            id: "Mengekstrak JSONB (->>) dengan ROW_NUMBER() dan mencatat clean_count serta reject_count ke ops.pipeline_runs.",
          },
          tags: ["PostgreSQL JSONB", "Quarantine", "TIMESTAMPTZ"],
          filePath: "pipelines/silver/build_silver.py",
          language: "python",
          code: `conn.execute(
    """
    INSERT INTO silver.rejected_records
    (pipeline_run_id, source_table, record_identifier, reject_reason, payload)
    SELECT %s, 'order_items', payload->>'order_item_id',
           'INVALID_QUANTITY_NEGATIVE_OR_ZERO', payload
    FROM bronze.raw_records
    WHERE pipeline_run_id = %s
      AND file_name = 'order_items.json'
      AND (payload->>'quantity')::INT <= 0
    """,
    (run_id, run_id),
)`,
        },
        {
          task_key: "quality_gate",
          layer: "GATE",
          pillClass: "pill-ops",
          defaultDurationMs: 2100,
          shortLabel: { en: "Silver Gate Check", id: "Gerbang Kualitas Silver" },
          desc: {
            en: "Runs run_silver_quality_gate and halts the Airflow DAG with AirflowException if negative quantities or orphan keys exist.",
            id: "Menjalankan run_silver_quality_gate dan menghentikan DAG dengan AirflowException bila ada kuantitas negatif atau orphan key.",
          },
          recruiterPoints: {
            en: [
              "Updates ops.pipeline_runs to FAILED with exact diagnostics upon gate violation.",
              "Prevents downstream Gold build from ever executing on invalid Silver state.",
            ],
            id: [
              "Memperbarui ops.pipeline_runs ke FAILED beserta pesan error tepat saat pelanggaran.",
              "Mencegah task Gold berjalan saat kondisi Silver bermasalah.",
            ],
          },
          businessImpact: {
            en: "Protects analytical SLA integrity by stopping broken runs early.",
            id: "Menjaga integritas SLA analitik dengan menghentikan eksekusi bermasalah lebih awal.",
          },
          engineerNotes: {
            en: "Audits silver_orders_exist, no_negative_qty_in_clean, 15 unique_keys, and referential_integrity.",
            id: "Mengaudit silver_orders_exist, no_negative_qty_in_clean, 15 unique_keys, dan referential_integrity.",
          },
          tags: ["AirflowException", "Circuit Breaker", "ops.quality_checks"],
          filePath: "pipelines/quality/checks.py",
          language: "python",
          code: `negative_qty_count = conn.execute(
    "SELECT COUNT(*) FROM silver.order_items WHERE pipeline_run_id = %s AND quantity <= 0",
    (run_id,)
).fetchone()[0]
c2_passed = (negative_qty_count == 0)
conn.execute(
    "INSERT INTO ops.quality_checks (run_id, check_name, check_stage, passed, details_json) "
    "VALUES (%s, 'no_negative_qty_in_clean', 'silver_gate', %s, %s)",
    (run_id, c2_passed, json.dumps({"negative_quantity_rows": int(negative_qty_count)})),
)`,
        },
        {
          task_key: "build_gold",
          layer: "GOLD",
          pillClass: "pill-gold",
          defaultDurationMs: 4200,
          shortLabel: { en: "Build 5 Gold Marts", id: "Bangun 5 Mart Gold" },
          desc: {
            en: "Builds the 5 PostgreSQL Gold tables via CTE pre-aggregation and ON CONFLICT DO UPDATE idempotent upserts.",
            id: "Membangun 5 tabel Gold PostgreSQL melalui pra-agregasi CTE dan upsert idempoten ON CONFLICT DO UPDATE.",
          },
          recruiterPoints: {
            en: [
              "Uses identical grain-safe SQL formulas to the Databricks Gold layer.",
              "Powers the 25/25 NL-to-SQL benchmark suite locally and on Neon/Postgres.",
            ],
            id: [
              "Menggunakan formula SQL grain-safe yang identik dengan layer Gold Databricks.",
              "Menyuplai 25/25 kueri benchmark NL-to-SQL secara lokal maupun di Neon/Postgres.",
            ],
          },
          businessImpact: {
            en: "Enables sub-50ms executive BI queries on normalized star/360 marts.",
            id: "Memungkinkan kueri BI eksekutif di bawah 50ms pada mart 360.",
          },
          engineerNotes: {
            en: "Computes dynamic return_status, promotion_count, first_order_flag, temporal product_categories, and web PURCHASE attribution.",
            id: "Menghitung return_status, promotion_count, first_order_flag, kategori temporal, dan atribusi web PURCHASE secara dinamis.",
          },
          tags: ["CTE Aggregation", "ON CONFLICT Upsert", "5 Gold Tables"],
          filePath: "pipelines/gold/build_gold.py",
          language: "python",
          code: `INSERT INTO gold.order_360 (...)
SELECT
    o.order_id, o.customer_id, o.ordered_at_utc::DATE AS order_date,
    o.sales_channel, o.store_id,
    COALESCE(i.gmv, 0), COALESCE(i.total_discount, 0), COALESCE(o.shipping_revenue, 0),
    COALESCE(p.total_captured, 0), COALESCE(r.total_refunded, 0),
    (COALESCE(i.gmv, 0) - COALESCE(i.total_discount, 0) + COALESCE(o.shipping_revenue, 0) - COALESCE(r.total_refunded, 0)) AS net_revenue,
    ...
ON CONFLICT (order_id) DO UPDATE SET net_revenue = EXCLUDED.net_revenue`,
        },
        {
          task_key: "validate_gold_and_record_metadata",
          layer: "RECON",
          pillClass: "pill-ops",
          defaultDurationMs: 1900,
          shortLabel: { en: "Reconcile & Mark Success", id: "Rekonsiliasi & Tandai Sukses" },
          desc: {
            en: "Executes Gold reconciliation checks and marks ops.pipeline_runs status = 'SUCCESS' with completed_at_utc.",
            id: "Menjalankan audit rekonsiliasi Gold dan menandai status ops.pipeline_runs = 'SUCCESS' beserta waktu selesai.",
          },
          recruiterPoints: {
            en: [
              "Ensures ops.pipeline_runs only transitions to SUCCESS after $0.00 financial drift is verified.",
              "Closes the full observability loop for operational monitoring.",
            ],
            id: [
              "Memastikan ops.pipeline_runs hanya menjadi SUCCESS setelah selisih finansial $0,00 terbukti.",
              "Melengkapi siklus observabilitas untuk pemantauan operasional.",
            ],
          },
          businessImpact: {
            en: "Signals downstream BI consumers and NL-to-SQL copilots that fresh data is audited and safe.",
            id: "Menandakan kepada pengguna BI dan Copilot NL-to-SQL bahwa data terbaru telah teraudit dan aman.",
          },
          engineerNotes: {
            en: "Calls run_gold_validation_and_reconciliation(run_id, target='local') and updates ops.pipeline_runs in one atomic commit.",
            id: "Memanggil run_gold_validation_and_reconciliation dan memperbarui ops.pipeline_runs dalam satu commit atomik.",
          },
          tags: ["$0.00 Parity", "Atomic Commit", "Lifecycle Audit"],
          filePath: "dags/dag.py",
          language: "python",
          code: `run_gold_validation_and_reconciliation(run_id, target="local")
with connect("local") as conn:
    conn.execute(
        """
        UPDATE ops.pipeline_runs
        SET status = 'SUCCESS',
            current_stage = 'completed',
            completed_at_utc = %s
        WHERE run_id = %s
        """,
        (datetime.now(UTC), run_id),
    )`,
        },
      ],
    },
  };

  const COPILOT_BENCHMARKS = [
    {
      question: "What is total net revenue by sales channel?",
      sql: "SELECT sales_channel, SUM(net_revenue) AS net_revenue FROM gold.order_360 GROUP BY sales_channel ORDER BY net_revenue DESC",
      explanation: {
        en: "Net revenue is aggregated at the order grain by sales channel ($13,561,301.58 total across all 4 omnichannel storefronts).",
        id: "Pendapatan bersih diagregasikan pada grain order per kanal penjualan (total $13.561.301,58 di keempat kanal omnichannel).",
      },
      tables_used: ["gold.order_360"],
      columns: ["sales_channel", "net_revenue"],
      rows: [
        { sales_channel: "WEB", net_revenue: 3473000.22 },
        { sales_channel: "STORE", net_revenue: 3386261.46 },
        { sales_channel: "MOBILE_APP", net_revenue: 3375258.14 },
        { sales_channel: "MARKETPLACE", net_revenue: 3326781.76 },
      ],
      visualization: { kind: "bar", title: "Net Revenue by Sales Channel", x: "sales_channel", y: ["net_revenue"] },
      execution_ms: 14,
    },
    {
      question: "Which product categories generated the most revenue?",
      sql: "SELECT active_category, SUM(net_revenue) AS net_revenue FROM gold.product_daily GROUP BY active_category ORDER BY net_revenue DESC",
      explanation: {
        en: "Product revenue is aggregated from product-day facts using temporal SCD2 active_category assignment (fashion leads at $3.30M).",
        id: "Pendapatan produk diagregasikan dari fakta produk-harian memakai kategori aktif temporal SCD2 (fashion memimpin di $3,30M).",
      },
      tables_used: ["gold.product_daily"],
      columns: ["active_category", "net_revenue"],
      rows: [
        { active_category: "fashion", net_revenue: 3300661.87 },
        { active_category: "electronics", net_revenue: 3120805.93 },
        { active_category: "sports", net_revenue: 2984213.34 },
        { active_category: "home", net_revenue: 2259052.5 },
        { active_category: "grocery", net_revenue: 2128875.33 },
        { active_category: "beauty", net_revenue: 1269408.57 },
        { active_category: "general", net_revenue: 2626.75 },
      ],
      visualization: { kind: "bar", title: "Net Revenue by Active Category", x: "active_category", y: ["net_revenue"] },
      execution_ms: 19,
    },
    {
      question: "Which campaigns had the best roas?",
      sql: "SELECT campaign_id, SUM(net_revenue) / NULLIF(SUM(campaign_spend), 0) AS roas FROM gold.channel_campaign_daily GROUP BY campaign_id HAVING SUM(campaign_spend) > 0 ORDER BY roas DESC",
      explanation: {
        en: "ROAS divides deterministic PURCHASE-attributed net revenue by campaign spend; CMP-04 leads at 46.97x ROAS.",
        id: "ROAS membagi pendapatan bersih ter-atribusi event PURCHASE dengan biaya kampanye; CMP-04 tertinggi di 46,97x ROAS.",
      },
      tables_used: ["gold.channel_campaign_daily"],
      columns: ["campaign_id", "roas"],
      rows: [
        { campaign_id: "CMP-04", roas: 46.9684 },
        { campaign_id: "CMP-05", roas: 46.3502 },
        { campaign_id: "CMP-02", roas: 45.8125 },
        { campaign_id: "CMP-01", roas: 45.801 },
        { campaign_id: "CMP-09", roas: 45.7732 },
        { campaign_id: "CMP-06", roas: 44.8626 },
        { campaign_id: "CMP-08", roas: 43.0664 },
        { campaign_id: "CMP-07", roas: 41.9613 },
      ],
      visualization: { kind: "bar", title: "Campaign ROAS Leaderboard", x: "campaign_id", y: ["roas"] },
      execution_ms: 17,
    },
    {
      question: "What was the daily net revenue?",
      sql: "SELECT metric_date, net_revenue FROM gold.executive_kpis_daily ORDER BY metric_date",
      explanation: {
        en: "Daily net revenue from the executive KPI contract (showing latest 7 verified days; peak on 2026-09-15 at $193,374.68).",
        id: "Pendapatan bersih harian dari kontrak KPI eksekutif (menampilkan 7 hari terverifikasi terbaru; puncak 2026-09-15 di $193.374,68).",
      },
      tables_used: ["gold.executive_kpis_daily"],
      columns: ["metric_date", "net_revenue"],
      rows: [
        { metric_date: "2026-09-13", net_revenue: 149527.46 },
        { metric_date: "2026-09-14", net_revenue: 144361.5 },
        { metric_date: "2026-09-15", net_revenue: 193374.68 },
        { metric_date: "2026-09-16", net_revenue: 133964.58 },
        { metric_date: "2026-09-17", net_revenue: 131195.93 },
        { metric_date: "2026-09-18", net_revenue: 145606.82 },
        { metric_date: "2026-09-19", net_revenue: 124333.06 },
      ],
      visualization: { kind: "line", title: "Daily Net Revenue", x: "metric_date", y: ["net_revenue"] },
      execution_ms: 12,
    },
    {
      question: "What was the daily stockout rate?",
      sql: "SELECT metric_date, stockout_rate FROM gold.executive_kpis_daily ORDER BY metric_date",
      explanation: {
        en: "Stockout rate averages product-day stockout flags across all inventory & sales rows (only 2026-06-24 recorded a 1.23% stockout spike; 90-day average is 0.01%).",
        id: "Rasio stockout merata-ratakan flag kehabisan stok harian (puncak tunggal 1,23% terjadi pada 2026-06-24; rata-rata 90 hari 0,01%).",
      },
      tables_used: ["gold.executive_kpis_daily"],
      columns: ["metric_date", "stockout_rate"],
      rows: [
        { metric_date: "2026-06-24", stockout_rate: 0.0123 },
        { metric_date: "2026-09-14", stockout_rate: 0.0 },
        { metric_date: "2026-09-15", stockout_rate: 0.0 },
        { metric_date: "2026-09-16", stockout_rate: 0.0 },
        { metric_date: "2026-09-17", stockout_rate: 0.0 },
        { metric_date: "2026-09-18", stockout_rate: 0.0 },
        { metric_date: "2026-09-19", stockout_rate: 0.0 },
      ],
      visualization: { kind: "line", title: "Daily Stockout Rate", x: "metric_date", y: ["stockout_rate"] },
      execution_ms: 11,
    },
    {
      question: "Which channels have the most repeat customers?",
      sql: "SELECT active_channel, COUNT(DISTINCT customer_id) AS repeat_customers FROM gold.customer_daily WHERE repeat_customer_flag GROUP BY active_channel ORDER BY repeat_customers DESC",
      explanation: {
        en: "Repeat customers are dynamically derived via first_order_flag windowing and grouped by active channel (STORE leads with 1,327 distinct repeat buyers).",
        id: "Pelanggan ulang diturunkan dinamis lewat window first_order_flag dan dikelompokkan per kanal aktif (STORE tertinggi dengan 1.327 pembeli berulang).",
      },
      tables_used: ["gold.customer_daily"],
      columns: ["active_channel", "repeat_customers"],
      rows: [
        { active_channel: "STORE", repeat_customers: 1327 },
        { active_channel: "MARKETPLACE", repeat_customers: 1311 },
        { active_channel: "WEB", repeat_customers: 1308 },
        { active_channel: "MOBILE_APP", repeat_customers: 1280 },
      ],
      visualization: { kind: "bar", title: "Repeat Customers by Channel", x: "active_channel", y: ["repeat_customers"] },
      execution_ms: 15,
    },
  ];

  global.MEDALLION_DATA = {
    DEFAULTS,
    I18N,
    VERIFIED_RUN_SNAPSHOT,
    VERIFIED_METRICS_SNAPSHOT,
    XRAY_STAGES,
    XRAY_ORDERS,
    STACKS,
    COPILOT_BENCHMARKS,
  };
})(window);
