import os
import json
import time
import html
from datetime import datetime
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types, errors
from pypdf import PdfReader
from docx import Document

# ---------- 1. SETUP ----------
load_dotenv()
def get_config(key, default=None):
    value = os.getenv(key)
    if value:
        return value
    try:
        return st.secrets[key]  # dipakai saat jalan di Streamlit Cloud
    except Exception:
        return default

API_KEY = get_config("GEMINI_API_KEY")
MODEL_NAME = get_config("GEMINI_MODEL", "gemini-3.5-flash")
MAX_CHARS = 15000  # batas teks yang dikirim ke AI (jaga kuota free tier)

SYSTEM_PROMPT = """
Kamu adalah asisten yang menganalisis laporan kegiatan operasional.
Baca SELURUH catatan dengan teliti, lalu keluarkan HANYA JSON dengan format:

{
  "summary": "ringkasan 2-4 kalimat",
  "issues": ["masalah 1", "masalah 2"],
  "action_items": [
    {"task": "tugas yang perlu dilakukan", "priority": "High|Medium|Low"}
  ],
  "status": "Selesai" atau "Perlu tindak lanjut"
}

Aturan umum:
- Gunakan HANYA informasi yang ada di laporan. Jangan mengarang.
- Jika tidak ada masalah, isi issues dengan ["Tidak disebutkan dalam laporan"].
- Jika tidak ada tindakan yang jelas, isi action_items dengan list kosong.
- Tulis dalam Bahasa Indonesia.

Aturan ringkasan:
- Ringkasan harus mencakup semua kejadian dan masalah utama, bukan hanya satu.
- Sertakan angka, jumlah, dan jam penting yang disebut di laporan, tulis persis seperti aslinya.

Aturan masalah:
- Periksa laporan kalimat demi kalimat. Setiap masalah yang berbeda ditulis sebagai satu butir sendiri, jangan digabung.
- Masalah kecil juga dicatat (misalnya perlengkapan rusak atau kedaluwarsa, lampu mati, stok habis, keterlambatan), meski disebut sekilas atau di tengah kalimat lain.
- Pahami singkatan dan bahasa informal sesuai konteks laporan.
- Sebelum menjawab, cek ulang bahwa tidak ada masalah di laporan yang belum masuk daftar issues.

Aturan action items:
- Buat minimal satu action item untuk setiap masalah yang belum selesai.
- Prioritas:
  - High: risiko keamanan atau keselamatan, peralatan penting rusak, masalah yang berulang atau sudah dilaporkan tetapi belum ditangani, atau yang menghambat operasional saat ini.
  - Medium: mengganggu pekerjaan tetapi ada solusi sementara.
  - Low: administratif, kenyamanan, atau perlengkapan habis.
"""

MODE_TYPE = "✍️ Ketik / tempel teks"
MODE_UPLOAD = "📎 Upload dokumen"

# State awal
st.session_state.setdefault("uploader_key", 0)
st.session_state.setdefault("history", [])

# ---------- 2. CSS ----------
# Ganti warna tema cukup lewat variabel di bagian :root ini.
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800&display=swap');

:root {
  --c-900: #1E3A5F;
  --c-700: #2F5D8C;
  --c-500: #4A7FAF;
  --c-300: #A9C1DC;
  --c-200: #CBD8E8;
  --c-100: #E3EBF5;
  --c-50:  #F4F7FB;
  --text:  #1E293B;
  --muted: #64748B;
  --shadow: rgba(47, 93, 140, 0.14);
}

html, body, .stApp, [class*="css"] { font-family: 'Poppins', sans-serif; }
.stApp { background: linear-gradient(180deg, var(--c-50) 0%, var(--c-100) 100%); }
.block-container { padding-top: 1.5rem; max-width: 960px; }
footer { visibility: hidden; }

/* Sidebar */
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, var(--c-100) 0%, #D6E1EF 100%);
  border-right: 1px solid var(--c-200);
}

/* Hero */
.hero {
  position: relative; overflow: hidden;
  background: linear-gradient(135deg, var(--c-900) 0%, var(--c-700) 60%, var(--c-500) 100%);
  border-radius: 24px; padding: 2rem 2.2rem; margin-bottom: 1.4rem;
  box-shadow: 0 12px 28px rgba(30, 58, 95, 0.28);
}
.hero::before {
  content: ""; position: absolute; width: 260px; height: 260px; border-radius: 50%;
  background: rgba(255,255,255,0.07); top: -90px; right: -60px;
}
.hero::after {
  content: ""; position: absolute; width: 160px; height: 160px; border-radius: 50%;
  background: rgba(255,255,255,0.06); bottom: -70px; right: 160px;
}
.hero h1 { color: #FFFFFF !important; font-weight: 800; font-size: 2.1rem; margin: .6rem 0 .3rem 0; padding: 0; line-height: 1.2; }
.hero p { color: #DCE6F2 !important; font-size: 1rem; margin: 0; max-width: 620px; position: relative; z-index: 1; }
.chip {
  display: inline-block; background: rgba(255,255,255,0.14); color: #FFFFFF;
  border: 1px solid rgba(255,255,255,0.28); border-radius: 999px;
  padding: .25rem .8rem; font-size: .78rem; font-weight: 600; margin-right: .5rem;
  position: relative; z-index: 1;
}

/* Sidebar: langkah cara pakai */
.side-step {
  display: flex; gap: 12px; align-items: flex-start; background: #FFFFFF;
  border: 1px solid var(--c-200); border-radius: 14px; padding: .7rem .8rem; margin-bottom: .6rem;
}
.side-step .num {
  flex: 0 0 28px; height: 28px; border-radius: 50%; color: #fff; font-weight: 700; font-size: .85rem;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, var(--c-700), var(--c-500));
}
.side-step .t { font-weight: 700; color: var(--c-900); font-size: .88rem; line-height: 1.3; }
.side-step .d { color: var(--muted); font-size: .76rem; line-height: 1.4; }

/* Kartu kosong */
.empty {
  background: rgba(255,255,255,0.65); border: 2px dashed var(--c-300); border-radius: 20px;
  padding: 1.6rem; text-align: center; color: var(--muted); margin-top: 1rem;
}
.empty b { color: var(--c-900); }

/* Kartu statistik */
.stat-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 1rem 0; }
.stat-card {
  display: flex; align-items: center; gap: 14px; background: #FFFFFF;
  border-radius: 18px; padding: 1rem 1.2rem; border: 1px solid var(--c-200);
  box-shadow: 0 6px 18px var(--shadow);
}
.stat-icon {
  width: 48px; height: 48px; border-radius: 14px; display: flex;
  align-items: center; justify-content: center; font-size: 1.4rem;
  background: var(--c-100);
}
.stat-value { font-size: 1.7rem; font-weight: 800; color: var(--c-700); line-height: 1.1; }
.stat-label { font-size: .78rem; color: var(--muted); font-weight: 500; }

/* Kartu hasil */
.card {
  background: #FFFFFF; border-radius: 20px; padding: 1.2rem 1.4rem; margin: .9rem 0;
  border: 1px solid var(--c-200); border-left: 6px solid var(--c-700);
  box-shadow: 0 6px 18px var(--shadow);
}
.card-title { font-weight: 700; color: var(--c-900); font-size: 1.05rem; margin-bottom: .5rem; }
.card p { color: var(--text); margin: 0; line-height: 1.65; }
.issue-list { margin: 0; padding-left: 1.1rem; color: var(--text); }
.issue-list li { margin: .3rem 0; }

/* Tabel action items */
table.ai-table { width: 100%; border-collapse: collapse; font-size: .9rem; }
table.ai-table th {
  text-align: left; background: var(--c-50); color: var(--c-900); padding: .6rem .8rem;
  border-bottom: 2px solid var(--c-200); font-weight: 700;
}
table.ai-table td { padding: .65rem .8rem; border-bottom: 1px solid #E2E8F0; color: var(--text); }
.badge { display: inline-block; padding: .2rem .75rem; border-radius: 999px; font-weight: 700; font-size: .75rem; }
.b-high { background: #FBE4E4; color: #A53030; }
.b-medium { background: #FBF0D9; color: #8A5A12; }
.b-low { background: #E2F3E7; color: #2E6B45; }

/* Status */
.status { border-radius: 16px; padding: .9rem 1.2rem; font-weight: 700; margin: .9rem 0; }
.status.warn { background: #FBF0D9; color: #7A4E0F; border: 1px solid #F0D79A; }
.status.ok { background: #E2F3E7; color: #245A3A; border: 1px solid #A8D8B9; }

/* Input */
.stTextArea textarea {
  border-radius: 16px; border: 2px solid var(--c-300); background: #FFFFFF; color: var(--text);
}
.stTextArea textarea:focus { border-color: var(--c-700); box-shadow: 0 0 0 3px rgba(47,93,140,0.18); }
[data-testid="stFileUploaderDropzone"] {
  border: 2px dashed var(--c-500); background: var(--c-50); border-radius: 18px;
}

/* Pilihan mode (radio jadi pill) */
div[role="radiogroup"] { gap: 10px; }
div[role="radiogroup"] label {
  background: #FFFFFF; border: 2px solid var(--c-200); border-radius: 999px;
  padding: .35rem 1.1rem; transition: all .2s;
}
div[role="radiogroup"] label:has(input:checked) {
  background: linear-gradient(135deg, var(--c-700), var(--c-500)); border-color: var(--c-700);
}
div[role="radiogroup"] label:has(input:checked) p { color: #FFFFFF !important; font-weight: 600; }

/* Tombol */
.stButton > button, .stDownloadButton > button {
  border-radius: 14px; font-weight: 600; padding: .65rem 1.3rem;
  border: 2px solid var(--c-700); color: var(--c-700); background: #FFFFFF; transition: all .2s;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  transform: translateY(-2px); box-shadow: 0 8px 18px var(--shadow);
  border-color: var(--c-900); color: var(--c-900);
}
.stButton > button[kind="primary"], .stButton > button[data-testid="stBaseButton-primary"] {
  background: linear-gradient(135deg, var(--c-700), var(--c-500)); color: #FFFFFF; border: none;
  box-shadow: 0 8px 18px rgba(47,93,140,0.28);
}
.stButton > button[kind="primary"]:hover, .stButton > button[data-testid="stBaseButton-primary"]:hover {
  color: #FFFFFF; box-shadow: 0 10px 22px rgba(47,93,140,0.4);
}

/* Tab */
.stTabs [role="tablist"] { gap: 10px; border-bottom: none !important; }
.stTabs button[role="tab"] {
  background: #FFFFFF !important;
  border: 1px solid var(--c-200) !important;
  border-radius: 14px !important;
  padding: .6rem 1.6rem !important;
  height: auto !important;
  min-width: 130px;
  justify-content: center;
}
.stTabs button[role="tab"] p { margin: 0 !important; font-weight: 600; color: var(--c-900) !important; }
.stTabs button[role="tab"][aria-selected="true"] {
  background: linear-gradient(135deg, var(--c-700), var(--c-500)) !important;
  border-color: var(--c-700) !important;
  box-shadow: 0 6px 14px rgba(47,93,140,0.25);
}
.stTabs button[role="tab"][aria-selected="true"] p { color: #FFFFFF !important; }
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] { display: none !important; }

@media (max-width: 700px) {
  .stat-grid { grid-template-columns: 1fr; }
  .hero h1 { font-size: 1.6rem; }
}
</style>
"""

# ---------- 3. FUNGSI ----------
def extract_text(uploaded) -> str:
    """Ambil teks dari file PDF / DOCX / TXT / CSV."""
    name = uploaded.name.lower()

    if name.endswith(".txt"):
        raw = uploaded.getvalue()
        for enc in ("utf-8", "latin-1"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return ""

    if name.endswith(".pdf"):
        reader = PdfReader(uploaded)
        return "\n".join((page.extract_text() or "") for page in reader.pages)

    if name.endswith(".docx"):
        doc = Document(uploaded)
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(c.text.strip() for c in row.cells))
        return "\n".join(parts)

    if name.endswith(".csv"):
        try:
            df = pd.read_csv(uploaded)
        except UnicodeDecodeError:
            uploaded.seek(0)
            df = pd.read_csv(uploaded, encoding="latin-1")
        return df.to_csv(index=False)

    return ""


def analyze_report(report_text: str, max_retries: int = 3) -> dict:
    client = genai.Client(api_key=API_KEY)
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=report_text,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            return json.loads(response.text)
        except errors.APIError as e:
            sementara = e.code in (429, 500, 503, 504)
            if sementara and attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise


def build_txt(result: dict) -> str:
    issues = result.get("issues", [])
    actions = result.get("action_items", [])
    return (
        f"RINGKASAN\n{result.get('summary', '')}\n\n"
        "MASALAH\n" + "\n".join(f"- {i}" for i in issues) + "\n\n"
        "ACTION ITEMS\n" + "\n".join(
            f"- [{a.get('priority', '-')}] {a.get('task', '')}" for a in actions
        ) + f"\n\nSTATUS: {result.get('status', '-')}"
    )


def reset_all():
    """Dipanggil tombol Selesai: kosongkan hasil, teks, dan file."""
    st.session_state.pop("result", None)
    st.session_state["report_input"] = ""
    st.session_state["uploader_key"] += 1  # ganti key = uploader kosong lagi


def stat_card(icon, label, value):
    return (
        f'<div class="stat-card"><div class="stat-icon">{icon}</div>'
        f'<div><div class="stat-value">{value}</div>'
        f'<div class="stat-label">{label}</div></div></div>'
    )


def card(title, body_html):
    return f'<div class="card"><div class="card-title">{title}</div>{body_html}</div>'


def priority_badge(p):
    p = str(p).strip().capitalize()
    css = {"High": "b-high", "Medium": "b-medium", "Low": "b-low"}.get(p, "b-medium")
    icon = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}.get(p, "🟡")
    return f'<span class="badge {css}">{icon} {html.escape(p)}</span>'


def side_step(num, title, desc):
    return (
        f'<div class="side-step"><div class="num">{num}</div>'
        f'<div><div class="t">{title}</div><div class="d">{desc}</div></div></div>'
    )


# ---------- 4. HALAMAN ----------
st.set_page_config(page_title="AI Report Assistant", page_icon="📝", layout="centered")
st.markdown(CSS, unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### 🎯 Cocok untuk")
    st.write(
        "Supervisor, koordinator, atau tim operasional yang sering menerima "
        "laporan panjang dan perlu cepat tahu apa yang harus ditindaklanjuti."
    )
    st.divider()

    st.markdown("### 🧭 Cara pakai")
    st.markdown(
        side_step(1, "Masukkan laporan", "Ketik catatan atau upload file PDF, Word, TXT, atau CSV.")
        + side_step(2, "Klik Analisis Laporan", "AI menyusun ringkasan, masalah, dan tugas berprioritas.")
        + side_step(3, "Unduh &amp; selesai", "Simpan hasil sebagai TXT atau CSV, lalu klik Selesai untuk mulai lagi."),
        unsafe_allow_html=True,
    )
    st.divider()

    st.caption("⚠️ Hasil AI tetap perlu diperiksa manual sebelum jadi laporan resmi.")
    
    st.caption(f"🤖 Model: {MODEL_NAME}")

st.markdown(
    """
<div class="hero">
<span class="chip">⚡ Powered by Gemini AI</span><span class="chip">PDF • DOCX • TXT • CSV</span>
<h1>📝 AI-Powered Report Assistant</h1>
<p>Mengubah catatan dan dokumen laporan yang berantakan jadi ringkasan dan action items berprioritas secara otomatis.</p>
</div>
""",
    unsafe_allow_html=True,
)

tab_hasil, tab_riwayat = st.tabs(["📊 Analisis", "🕘 Riwayat"])

# ---------- 5. TAB ANALISIS ----------
with tab_hasil:
    mode = st.radio(
        "Sumber laporan",
        [MODE_TYPE, MODE_UPLOAD],
        horizontal=True,
        key="mode",
        label_visibility="collapsed",
    )

    report_text = ""
    source_label = "Teks manual"

    if mode == MODE_TYPE:
        report_text = st.text_area(
            "Tempel catatan laporan di sini:",
            height=180,
            key="report_input",
            placeholder="Contoh: Hari ini tim melakukan pengecekan peralatan di lokasi A. Ditemukan dua CCTV tidak berfungsi...",
        )
    else:
        uploaded = st.file_uploader(
            "Upload laporan (PDF, DOCX, TXT, CSV)",
            type=["pdf", "docx", "txt", "csv"],
            key=f"uploader_{st.session_state['uploader_key']}",
        )
        if uploaded is not None:
            source_label = uploaded.name
            try:
                report_text = extract_text(uploaded)
            except Exception as e:
                st.error(f"Gagal membaca file: {e}")
            if report_text.strip():
                with st.expander(f"👀 Lihat teks yang terbaca dari {uploaded.name}"):
                    st.text(report_text[:3000] + ("..." if len(report_text) > 3000 else ""))
            else:
                st.warning(
                    "Tidak ada teks yang terbaca. Kalau ini PDF hasil scan (berupa gambar), "
                    "aplikasi ini belum bisa membacanya."
                )

    col_a, col_b = st.columns([2, 1])
    analyze = col_a.button("🚀 Analisis Laporan", type="primary", use_container_width=True)
    col_b.button("✅ Selesai", on_click=reset_all, use_container_width=True)

    if analyze:
        teks = report_text.strip()
        if not API_KEY:
            st.error("API key belum diisi. Cek file .env lu.")
        elif not teks:
            st.warning("Isi dulu laporannya, ketik teks atau upload dokumen.")
        else:
            if len(teks) > MAX_CHARS:
                teks = teks[:MAX_CHARS]
                st.info(f"Dokumen panjang, hanya {MAX_CHARS:,} karakter pertama yang dianalisis.")
            try:
                with st.spinner("AI lagi menganalisis... (kalau server sibuk, dicoba ulang otomatis)"):
                    result = analyze_report(teks)
                st.session_state["result"] = result

                actions = result.get("action_items", [])
                n_high = sum(1 for a in actions if str(a.get("priority", "")).lower() == "high")
                st.session_state["history"].append({
                    "waktu": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "sumber": source_label,
                    "ringkasan": result.get("summary", ""),
                    "status": result.get("status", ""),
                    "jumlah_action": len(actions),
                    "prioritas_high": n_high,
                })
            except json.JSONDecodeError:
                st.error("AI mengembalikan format yang tidak valid. Coba klik analisis lagi.")
            except errors.APIError as e:
                if e.code == 429:
                    st.error("Kuota gratis model ini habis (error 429). Ganti model di .env atau coba lagi nanti.")
                elif e.code == 503:
                    st.error("Server Gemini lagi sibuk (error 503). Tunggu beberapa menit lalu coba lagi.")
                else:
                    st.error(f"Terjadi error dari API (kode {e.code}).")
                with st.expander("Detail error (untuk debugging)"):
                    st.code(str(e))
            except Exception as e:
                st.error(f"Terjadi error: {e}")

    # ----- Tampilan hasil -----
    result = st.session_state.get("result")
    if result:
        summary = html.escape(str(result.get("summary", "-")))
        issues = result.get("issues", [])
        actions = result.get("action_items", [])
        status = str(result.get("status", "-"))

        n_issues = 0 if issues == ["Tidak disebutkan dalam laporan"] else len(issues)
        n_high = sum(1 for a in actions if str(a.get("priority", "")).lower() == "high")

        st.markdown(
            '<div class="stat-grid">'
            + stat_card("⚠️", "Masalah ditemukan", n_issues)
            + stat_card("📋", "Action items", len(actions))
            + stat_card("🔥", "Prioritas High", n_high)
            + "</div>",
            unsafe_allow_html=True,
        )

        if "tindak lanjut" in status.lower():
            st.markdown(f'<div class="status warn">⏳ Status: {html.escape(status)}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="status ok">✅ Status: {html.escape(status)}</div>', unsafe_allow_html=True)

        st.markdown(card("📌 Ringkasan", f"<p>{summary}</p>"), unsafe_allow_html=True)

        issue_html = "<ul class='issue-list'>" + "".join(
            f"<li>{html.escape(str(i))}</li>" for i in issues
        ) + "</ul>"
        st.markdown(card("🔍 Masalah yang teridentifikasi", issue_html), unsafe_allow_html=True)

        if actions:
            rows = "".join(
                f"<tr><td>{html.escape(str(a.get('task', '')))}</td>"
                f"<td>{priority_badge(a.get('priority', ''))}</td></tr>"
                for a in actions
            )
            table = f'<table class="ai-table"><tr><th>Tugas</th><th>Prioritas</th></tr>{rows}</table>'
        else:
            table = "<p>Tidak ada action item.</p>"
        st.markdown(card("✅ Action items", table), unsafe_allow_html=True)

        df = pd.DataFrame(actions) if actions else pd.DataFrame(columns=["task", "priority"])
        d1, d2 = st.columns(2)
        d1.download_button("⬇️ Download TXT", build_txt(result), "laporan.txt", use_container_width=True)
        d2.download_button("⬇️ Download CSV", df.to_csv(index=False), "action_items.csv", use_container_width=True)
    else:
        st.markdown(
            '<div class="empty">📄 <b>Hasil analisis akan tampil di sini.</b><br>'
            "Masukkan laporan di atas, lalu klik Analisis Laporan.</div>",
            unsafe_allow_html=True,
        )

# ---------- 6. TAB RIWAYAT ----------
with tab_riwayat:
    if st.session_state["history"]:
        hist_df = pd.DataFrame(st.session_state["history"])
        st.dataframe(hist_df, hide_index=True)
        st.download_button("⬇️ Download riwayat (CSV)", hist_df.to_csv(index=False), "riwayat_analisis.csv")
    else:
        st.info("Belum ada laporan yang dianalisis di sesi ini.")