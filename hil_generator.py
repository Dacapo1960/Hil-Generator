"""
HIL Generator · A320 · ASL GmbH
================================
Streamlit-App zur automatischen Erstellung von Hold Item Lists (HIL)
auf Basis von MEL-Einträgen (Airbus A320).

INSTALLATION (einmalig, Terminal/Cmd):
    pip install streamlit anthropic

STARTEN:
    streamlit run hil_generator.py

API KEY:
    In der Sidebar der App eingeben, oder als Umgebungsvariable:
    Windows:   set ANTHROPIC_API_KEY=sk-ant-...
    Mac/Linux: export ANTHROPIC_API_KEY=sk-ant-...
"""

import os
import json
import random
import re
from datetime import datetime, timedelta

import anthropic
import streamlit as st

# ── Seitenkonfiguration ────────────────────────────────────────────────────────

st.set_page_config(
    page_title="HIL Generator · A320",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Systemfarben ───────────────────────────────────────────────────────────────

HEADER_BG  = "#1F3864"
SEC_BG     = "#2E75B6"
OPR_BG     = "#375623"
OPR_LT     = "#EBF3E8"
LABEL_BG   = "#D5E8F0"
OPEN_BG    = "#FCE4D6"
OPEN_TXT   = "#C00000"
BORDER     = "#9DC3E6"
BORDER_DK  = "#1F3864"

# ── System-Prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an Airbus A320/A321 MMEL (Master Minimum Equipment List) expert.
Given a defect description, return ONLY a raw JSON object. No markdown fences, no explanation.

{
  "mel_ref":            "ATA chapter-item e.g. 32-42-01",
  "mel_category":       "CAT A|B|C|D",
  "ata_chapter":        "e.g. ATA 32 - Landing Gear",
  "duration_days":      10,
  "discrepancy":        "Formal MEL discrepancy statement, 1-2 sentences, exactly as written in the MEL",
  "flight_limitations": "Exact MEL operational limitations, or Nil",
  "has_o_proc":         false,
  "o_procedures":       [],
  "has_m_proc":         true,
  "m_procedures":       "Exact maintenance action as written in MEL, including test requirements"
}

CRITICAL RULES - strictly follow:
1. ACCURACY: Reproduce only what the actual Airbus A320/A321 MMEL contains. Do NOT invent procedures.
2. O-PROCEDURE (Operational, performed by crew): Set has_o_proc=true ONLY if the real MMEL explicitly requires a crew operational procedure for this item. Many MEL items have NO O-procedure (e.g. BSCU faults, sensor failures, most avionics failures). If unsure, set has_o_proc=false.
3. M-PROCEDURE (Maintenance, performed by licensed engineer): Set has_m_proc=true for nearly all items. Write the actual maintenance action concisely.
4. DISCREPANCY: Use formal MEL language, not free text.
5. FLIGHT_LIMITATIONS: State exact MEL restrictions (e.g. "Dispatch only with system X operative"). Use "Nil" if no restrictions.
6. Raw JSON only, no explanation, no markdown.
"""

# ── HTML-Hilfsfunktionen ───────────────────────────────────────────────────────

def td_style(bg=None, bold=False, color="#000", border_color=BORDER,
             italic=False, colspan=1, align="left", extra=""):
    bg_str = f"background-color:{bg};" if bg else ""
    fw = "bold" if bold else "normal"
    fs = "italic" if italic else "normal"
    cs = f' colspan="{colspan}"' if colspan > 1 else ""
    return (f'<td{cs} style="border:1px solid {border_color};padding:5px 8px;'
            f'font-family:Arial,sans-serif;font-size:10.5pt;{bg_str}'
            f'color:{color};font-weight:{fw};font-style:{fs};'
            f'vertical-align:top;text-align:{align};{extra}">')

def section_header(text, bg=SEC_BG, color="white"):
    return (f'<tr><td colspan="4" style="background-color:{bg};color:{color};'
            f'font-weight:bold;font-size:10.5pt;font-family:Arial,sans-serif;'
            f'padding:5px 8px;border:1px solid {BORDER_DK};">'
            f'{text}</td></tr>')

def text_row(content, bg="white", bold=False):
    fw = "bold" if bold else "normal"
    return (f'<tr><td colspan="4" style="background-color:{bg};'
            f'font-size:10.5pt;font-family:Arial,sans-serif;padding:5px 8px;'
            f'border:1px solid {BORDER};white-space:pre-wrap;font-weight:{fw};">'
            f'{content}</td></tr>')

def label_val_row(l1, v1, l2, v2, v1_bold=False, v1_color="#000",
                  v2_bold=False, w1=18, w2=32, w3=18, w4=32):
    fw1 = "bold" if v1_bold else "normal"
    fw2 = "bold" if v2_bold else "normal"
    return (
        f'<tr>'
        f'<td style="width:{w1}%;background-color:{LABEL_BG};font-weight:bold;'
        f'border:1px solid {BORDER};padding:5px 8px;font-family:Arial,sans-serif;font-size:10.5pt;">{l1}</td>'
        f'<td style="width:{w2}%;border:1px solid {BORDER};padding:5px 8px;'
        f'font-family:Arial,sans-serif;font-size:10.5pt;font-weight:{fw1};color:{v1_color};">{v1}</td>'
        f'<td style="width:{w3}%;background-color:{LABEL_BG};font-weight:bold;'
        f'border:1px solid {BORDER};padding:5px 8px;font-family:Arial,sans-serif;font-size:10.5pt;">{l2}</td>'
        f'<td style="width:{w4}%;border:1px solid {BORDER};padding:5px 8px;'
        f'font-family:Arial,sans-serif;font-size:10.5pt;font-weight:{fw2};">{v2}</td>'
        f'</tr>'
    )

def build_hil_html(h: dict, printable: bool = False) -> str:
    """Erzeugt den vollständigen HTML-String der HIL."""

    # O-Procedure Zeilen
    o_rows = ""
    if h.get("has_o_proc") and h.get("o_procedures"):
        procs = h["o_procedures"]
        n = len(procs)
        items_html = ""
        for i, step in enumerate(procs):
            is_critical = i >= max(0, n - 2)
            fw = "bold" if is_critical else "normal"
            items_html += (f'<div style="margin-bottom:3px;font-weight:{fw};">'
                           f'{i+1}.&nbsp;&nbsp;{step}</div>')
        o_rows = (
            section_header("(O)  OPERATIONAL PROCEDURE  ·  Flight Crew", OPR_BG) +
            f'<tr><td colspan="4" style="background-color:{OPR_LT};border:1px solid {BORDER};'
            f'padding:5px 8px;font-family:Arial,sans-serif;font-size:10.5pt;">{items_html}</td></tr>'
        )

    # M-Procedure Zeilen
    m_rows = ""
    if h.get("has_m_proc") and h.get("m_procedures"):
        m_rows = (section_header("(M)  MAINTENANCE PROCEDURE  ·  Maintenance Action") +
                  text_row(h["m_procedures"]))

    page_break = '@page { size: A4; margin: 1.5cm; }' if printable else ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: Arial, sans-serif; margin: {'0' if printable else '20px'}; background: white; }}
  table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
  {page_break}
  .no-print {{ display: {'none' if printable else 'block'}; }}
  @media print {{ .no-print {{ display: none; }} body {{ margin: 0; }} }}
</style>
</head>
<body>

<div class="no-print" style="margin-bottom:16px;">
  <button onclick="window.print()"
    style="background:{HEADER_BG};color:white;border:none;padding:8px 18px;
           border-radius:4px;font-size:13px;font-weight:bold;cursor:pointer;">
    🖨️  Drucken / Als PDF speichern
  </button>
</div>

<table>
  <colgroup>
    <col style="width:18%"><col style="width:32%">
    <col style="width:18%"><col style="width:32%">
  </colgroup>
  <tbody>

    <!-- Titel -->
    <tr><td colspan="4" style="background-color:{HEADER_BG};color:white;text-align:center;
      font-weight:bold;font-size:14pt;font-family:Arial,sans-serif;
      padding:8px;border:2px solid {BORDER_DK};letter-spacing:1px;">
      HOLD ITEM LIST (HIL)
    </td></tr>

    {label_val_row("Operator", h.get("operator",""), "Aircraft Type", h.get("ac_type",""))}
    {label_val_row("Registration", h.get("registration",""), "Flight No.", h.get("flight_no","—"))}
    {label_val_row("HIL No.", h.get("hil_no",""), "MEL Reference", h.get("mel_ref",""))}
    {label_val_row("MEL Category",
                   f'{h.get("mel_category","")} · {h.get("duration_days","")} Calendar Days',
                   "ATA Chapter", h.get("ata_chapter",""),
                   v1_bold=True, v1_color=OPEN_TXT)}
    {label_val_row("Date Created", h.get("date_created",""), "Due Date",
                   h.get("due_date",""), v2_bold=True)}

    {section_header("DISCREPANCY")}
    {text_row(h.get("discrepancy",""))}

    {section_header("FLIGHT LIMITATIONS")}
    {text_row(h.get("flight_limitations",""))}

    {o_rows}
    {m_rows}

    {label_val_row("Maintenance Release No.", h.get("mr_no",""), "Authorized Date", h.get("auth_date",""))}
    {label_val_row("Maintenance Engineer", h.get("engineer",""), "Signature", "")}

    <!-- Status -->
    <tr>
      <td colspan="2" style="background-color:{OPEN_BG};border:2px solid {BORDER_DK};padding:6px 8px;">
        <div style="font-size:9pt;font-weight:bold;color:#555;font-family:Arial;">Status</div>
        <div style="font-size:18pt;font-weight:bold;color:{OPEN_TXT};font-family:Arial;">OPEN</div>
      </td>
      <td colspan="2" style="background-color:{OPEN_BG};border:2px solid {BORDER_DK};padding:6px 8px;">
        <div style="font-size:9pt;font-weight:bold;color:#555;font-family:Arial;">Days Remaining</div>
        <div style="font-size:18pt;font-weight:bold;color:{OPEN_TXT};font-family:Arial;">{h.get("days_remaining","")}</div>
      </td>
    </tr>

  </tbody>
</table>
</body>
</html>"""
    return html

# ── API-Aufruf ─────────────────────────────────────────────────────────────────

def generate_from_api(defect: str, api_key: str) -> dict:
    """Ruft Claude API auf und gibt geparste MEL-Daten zurück."""
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"A320 defect: {defect}"}],
    )
    raw = message.content[0].text
    raw = re.sub(r"```json\n?|```", "", raw).strip()
    return json.loads(raw)

# ── Hilfsfunktion: Datumskalkulation ──────────────────────────────────────────

def fmt_de(d: datetime) -> str:
    return d.strftime("%d.%m.%Y")

# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ✈️ HIL Generator · A320")
    st.markdown("---")

    api_key = st.text_input(
        "Anthropic API Key",
        type="password",
        value=st.secrets.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", "")),
        help="Von console.anthropic.com · sk-ant-…",
    )

    st.markdown("---")
    st.markdown("**Anleitung**")
    st.markdown(
        "1. API Key eingeben\n"
        "2. Felder ausfüllen\n"
        "3. **HIL generieren** klicken\n"
        "4. Inhalt prüfen / bearbeiten\n"
        "5. **Als HTML speichern** → Browser öffnen → Drucken"
    )
    st.markdown("---")
    st.caption("ASL GmbH · Trainingsflug · A320")

# ── Hauptseite ─────────────────────────────────────────────────────────────────

st.title("HIL Generator · A320")
st.caption("Fehler eingeben → MEL-Referenz, Kategorie und O/M-Procedure werden automatisch ermittelt.")
st.markdown("---")

# Session State initialisieren
if "hil" not in st.session_state:
    st.session_state.hil = None
if "generated" not in st.session_state:
    st.session_state.generated = False

# ── Eingabeformular ────────────────────────────────────────────────────────────

with st.form("hil_form"):
    col1, col2 = st.columns(2)
    with col1:
        registration = st.text_input("Registration", value="D-AXXX")
        operator     = st.text_input("Operator",     value="ASL GmbH")
    with col2:
        ac_type   = st.text_input("Aircraft Type",
                                  value="A320-212 (CFM56-5B)")
        flight_no = st.text_input("Flight No. (optional)",
                                  placeholder="z.B. ABC 1234 (LOFT M1)")

    defect = st.text_area(
        "Fehler / Defect *",
        placeholder=(
            "Beispiele:\n"
            "• FUEL L WING TK PUMP 2 INOP\n"
            "• BSCU CHANNEL 1 failed BITE during pre-flight inspection\n"
            "• ELAC 2 inoperative\n"
            "• Cabin reading light row 23 inoperative"
        ),
        height=110,
    )

    submitted = st.form_submit_button("🔄  HIL generieren", type="primary",
                                      use_container_width=True)

# ── Generierung ────────────────────────────────────────────────────────────────

if submitted:
    if not api_key:
        st.error("Kein API Key angegeben. Bitte in der Sidebar eintragen.")
    elif not defect.strip():
        st.error("Bitte einen Fehler beschreiben.")
    else:
        with st.spinner("MEL-Eintrag wird generiert…"):
            try:
                parsed = generate_from_api(defect.strip(), api_key)

                today = datetime.now()
                days  = int(parsed.get("duration_days", 10))
                due   = today + timedelta(days=days)
                hil_no = f"HIL-{today.year}-{random.randint(100, 999)}"

                st.session_state.hil = {
                    # Aircraft
                    "registration": registration,
                    "operator":     operator,
                    "ac_type":      ac_type,
                    "flight_no":    flight_no,
                    # HIL-Metadaten
                    "hil_no":       hil_no,
                    "date_created": fmt_de(today),
                    "due_date":     fmt_de(due),
                    "days_remaining": str(days),
                    "auth_date":    fmt_de(today),
                    "mr_no":        f"MR-{today.year}-____",
                    "engineer":     "________________________________",
                    # Generiert
                    "mel_ref":          parsed.get("mel_ref", ""),
                    "mel_category":     parsed.get("mel_category", ""),
                    "ata_chapter":      parsed.get("ata_chapter", ""),
                    "duration_days":    days,
                    "discrepancy":      parsed.get("discrepancy", ""),
                    "flight_limitations": parsed.get("flight_limitations", "Nil"),
                    "has_o_proc":       parsed.get("has_o_proc", True),
                    "o_procedures":     parsed.get("o_procedures", []),
                    "has_m_proc":       parsed.get("has_m_proc", True),
                    "m_procedures":     parsed.get("m_procedures", ""),
                }
                st.session_state.generated = True
                st.success(f"Generiert: {parsed.get('mel_ref','')} · "
                           f"{parsed.get('mel_category','')} · "
                           f"{parsed.get('ata_chapter','')}")

            except json.JSONDecodeError as e:
                st.error(f"JSON-Parsing fehlgeschlagen: {e}")
            except Exception as e:
                st.error(f"Fehler: {e}")

# ── Bearbeiten & Vorschau ──────────────────────────────────────────────────────

if st.session_state.hil:
    h = st.session_state.hil
    st.markdown("---")

    with st.expander("✏️  Inhalt bearbeiten", expanded=False):
        st.caption("Alle Felder sind korrigierbar. Änderungen werden sofort in der Vorschau übernommen.")
        ec1, ec2 = st.columns(2)

        with ec1:
            h["registration"]  = st.text_input("Registration",          value=h["registration"])
            h["flight_no"]     = st.text_input("Flight No.",             value=h["flight_no"])
            h["mel_ref"]       = st.text_input("MEL Reference",          value=h["mel_ref"])
            h["mel_category"]  = st.text_input("MEL Category",           value=h["mel_category"])
            h["ata_chapter"]   = st.text_input("ATA Chapter",            value=h["ata_chapter"])
            days_edit          = st.text_input("Duration (Calendar Days)",value=str(h["duration_days"]))
            h["due_date"]      = st.text_input("Due Date",               value=h["due_date"])
            h["hil_no"]        = st.text_input("HIL No.",                value=h["hil_no"])
            h["mr_no"]         = st.text_input("Maintenance Release No.",value=h["mr_no"])
            h["engineer"]      = st.text_input("Maintenance Engineer",   value=h["engineer"])
            try:
                h["duration_days"] = int(days_edit)
                h["days_remaining"] = days_edit
            except ValueError:
                pass

        with ec2:
            h["discrepancy"]        = st.text_area("Discrepancy",
                                                    value=h["discrepancy"], height=90)
            h["flight_limitations"] = st.text_area("Flight Limitations",
                                                    value=h["flight_limitations"], height=70)
            opr_text = "\n".join(h.get("o_procedures", []))
            opr_edit = st.text_area("(O) Procedure — eine Zeile pro Schritt",
                                    value=opr_text, height=150)
            h["o_procedures"] = [l for l in opr_edit.split("\n") if l.strip()]
            h["m_procedures"] = st.text_area("(M) Procedure",
                                             value=h["m_procedures"], height=80)

        st.session_state.hil = h

    # Vorschau
    st.markdown("### HIL Vorschau")
    preview_html = build_hil_html(h, printable=False)
    st.components.v1.html(preview_html, height=820, scrolling=True)

    # Download
    st.markdown("---")
    printable_html = build_hil_html(h, printable=True)
    filename = f"HIL_{h['hil_no']}_{h['registration'].replace(' ','_')}_{h['mel_ref'].replace('-','_')}.html"

    col_dl, col_hint = st.columns([1, 3])
    with col_dl:
        st.download_button(
            label="💾  Als HTML speichern",
            data=printable_html,
            file_name=filename,
            mime="text/html",
            use_container_width=True,
            type="primary",
        )
    with col_hint:
        st.info(
            "**HTML-Datei öffnen → Strg+P (Drucken) → Zieldrucker: PDF speichern** "
            "→ direkt ans SimBrief-Paket anhängen."
        )

    # Neue HIL
    if st.button("🔄  Neue HIL generieren", use_container_width=True):
        st.session_state.hil = None
        st.session_state.generated = False
        st.rerun()
