import io
import json
import os
from pathlib import Path
import pickle
import re
import sys
import time

import streamlit as st

try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    from PIL import Image
except ImportError:
    Image = None


BASE_DIR = Path(__file__).resolve().parent
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_VISION_MODEL = "models/gemini-2.5-flash"

SESSION_DEFAULTS = {
    "diabetes_pregnancies": 0,
    "diabetes_bmi": 25.0,
    "diabetes_glucose": 100,
    "diabetes_age": 30,
    "diabetes_bp": 80,
    "heart_age": 45,
    "heart_rate": 150,
    "cholesterol": 200,
    "oldpeak": 1.0,
    "liver_age": 35,
    "direct_bilirubin": 0.5,
    "total_bilirubin": 1.0,
    "albumin": 3.0,
}

REPORT_LABELS = {
    "glucose": "Glucose",
    "blood_pressure": "Blood Pressure",
    "age": "Age",
    "bmi": "BMI",
    "pregnancies": "Pregnancies",
    "heart_rate": "Heart Rate",
    "cholesterol": "Cholesterol",
}


def load_model(model_name):
    with (BASE_DIR / model_name).open("rb") as model_file:
        return pickle.load(model_file)


def init_session_state():
    for key, value in SESSION_DEFAULTS.items():
        st.session_state.setdefault(key, value)

    st.session_state.setdefault("extracted_report_values", {})


def extract_json_from_text(raw_text):
    cleaned_text = raw_text.strip().replace("```json", "").replace("```", "").strip()
    match = re.search(r"\{.*\}", cleaned_text, re.DOTALL)
    if not match:
        raise ValueError("Gemini did not return valid JSON.")

    return json.loads(match.group(0))


def coerce_number(value, integer=False, default=None):
    if value is None:
        return default

    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text_value = str(value).strip()
        if not text_value or text_value.lower() in {"none", "null", "n/a", "na", "not available"}:
            return default

        match = re.search(r"-?\d+(?:\.\d+)?", text_value.replace(",", ""))
        if not match:
            return default

        number = float(match.group(0))

    if integer:
        return int(round(number))

    return float(number)


def normalize_report_values(payload):
    return {
        "glucose": coerce_number(payload.get("glucose"), integer=True),
        "blood_pressure": coerce_number(payload.get("blood_pressure"), integer=True),
        "age": coerce_number(payload.get("age"), integer=True),
        "bmi": coerce_number(payload.get("bmi")),
        "pregnancies": coerce_number(payload.get("pregnancies"), integer=True, default=0),
        "heart_rate": coerce_number(payload.get("heart_rate"), integer=True),
        "cholesterol": coerce_number(payload.get("cholesterol"), integer=True),
    }


def get_gemini_module():
    global genai

    if genai is None:
        try:
            import google.generativeai as genai_module
            genai = genai_module
        except ImportError as exc:
            raise RuntimeError(
                f"Install google-generativeai to use Gemini features. Current interpreter: {sys.executable}"
            ) from exc

    return genai


def get_gemini_model(model_name):
    if GOOGLE_API_KEY == "YOUR_GOOGLE_API_KEY_HERE":
        raise RuntimeError("Add your GOOGLE_API_KEY in the GOOGLE_API_KEY placeholder first.")

    clear_dead_local_proxy()
    gemini = get_gemini_module()
    gemini.configure(api_key=GOOGLE_API_KEY)
    return gemini.GenerativeModel(model_name)


def clear_dead_local_proxy():
    dead_proxy = "http://127.0.0.1:9"
    proxy_keys = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    )

    for key in proxy_keys:
        if os.environ.get(key) == dead_proxy:
            os.environ.pop(key, None)


def extract_report_values(image_bytes):
    if Image is None:
        try:
            from PIL import Image as pil_image
            Image = pil_image
        except ImportError as exc:
            raise RuntimeError(
                f"Install pillow to use report upload. Current interpreter: {sys.executable}"
            ) from exc

    model = get_gemini_model(GEMINI_VISION_MODEL)
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    image.thumbnail((1400, 1400))

    prompt = """
    You are reading a blood test or medical report image.
    Extract only these values and return strict JSON:
    {
      "glucose": number or null,
      "blood_pressure": number or null,
      "age": number or null,
      "bmi": number or null,
      "pregnancies": number,
      "heart_rate": number or null,
      "cholesterol": number or null
    }

    Rules:
    - Use only numeric values, no units.
    - If blood pressure is written like 120/80, return the systolic value as blood_pressure.
    - If pregnancies is missing, use 0.
    - If any other value is missing, use null.
    - Do not add any extra keys or explanation.
    """

    try:
        response = model.generate_content(
            [prompt, image],
            generation_config={"temperature": 0},
            request_options={"timeout": 30},
        )
    except Exception as exc:
        error_text = str(exc).lower()
        if "quota" in error_text or "429" in error_text or "resource_exhausted" in error_text:
            raise RuntimeError("Gemini API quota exceeded. Please wait a minute and try again.") from exc
        if "timeout" in error_text or "deadline" in error_text:
            raise RuntimeError("Gemini request timed out. Upload a smaller, clearer image and try again.") from exc
        raise RuntimeError(f"Gemini extraction failed: {exc}") from exc

    raw_text = getattr(response, "text", "") or ""
    return normalize_report_values(extract_json_from_text(raw_text))


def apply_extracted_values(values):
    value_map = {
        "glucose": ["diabetes_glucose"],
        "blood_pressure": ["diabetes_bp"],
        "age": ["diabetes_age", "heart_age", "liver_age"],
        "bmi": ["diabetes_bmi"],
        "pregnancies": ["diabetes_pregnancies"],
        "heart_rate": ["heart_rate"],
        "cholesterol": ["cholesterol"],
    }

    for field_name, targets in value_map.items():
        field_value = values.get(field_name)
        if field_value is None:
            continue

        for target in targets:
            st.session_state[target] = field_value


st.set_page_config(
    page_title="NeuroHealth AI 2026",
    layout="wide",
    page_icon="🧬",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root {
        --text-main: #f5f7fb;
        --text-muted: #c0cddd;
        --accent-main: #4f9cf9;
        --accent-strong: #1f5fbf;
        --glass-bg: rgba(10, 23, 37, 0.52);
        --glass-strong: rgba(7, 18, 29, 0.74);
        --glass-border: rgba(255, 255, 255, 0.12);
        --glass-shadow: 0 18px 40px rgba(0, 0, 0, 0.24);
    }

    .stApp {
        background:
            radial-gradient(circle at 18% 12%, rgba(117, 186, 255, 0.18), transparent 26%),
            radial-gradient(circle at 84% 8%, rgba(79, 156, 249, 0.22), transparent 24%),
            linear-gradient(180deg, #09131e 0%, #11283d 54%, #16334f 100%);
        color: var(--text-main);
    }

    [data-testid="stHeader"] {
        background: transparent;
    }

    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }

    h1, h2, h3, label, span {
        color: var(--text-main);
    }

    p {
        color: var(--text-muted);
    }

    .hero-panel {
        background: linear-gradient(135deg, rgba(12, 27, 43, 0.74) 0%, rgba(17, 41, 63, 0.52) 100%);
        border: 1px solid var(--glass-border);
        border-radius: 28px;
        padding: 1.6rem 1.8rem;
        margin-bottom: 1.4rem;
        backdrop-filter: blur(18px);
        box-shadow: var(--glass-shadow);
    }

    .hero-kicker {
        display: inline-block;
        padding: 0.35rem 0.8rem;
        border-radius: 999px;
        background: rgba(79, 156, 249, 0.14);
        border: 1px solid rgba(79, 156, 249, 0.24);
        color: #d8ebff;
        font-size: 0.8rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin-bottom: 0.9rem;
    }

    .hero-title {
        margin: 0;
        font-size: clamp(2rem, 4vw, 3.2rem);
        line-height: 1.05;
        color: #eef7ff;
    }

    .hero-subtitle {
        margin: 0.75rem 0 0;
        max-width: 42rem;
        font-size: 1rem;
        color: var(--text-muted);
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(6, 15, 25, 0.95) 0%, rgba(12, 27, 43, 0.94) 100%);
        border-right: 1px solid rgba(255, 255, 255, 0.08);
        box-shadow: 10px 0 30px rgba(0, 0, 0, 0.16);
    }

    [data-testid="stSidebar"] * {
        color: var(--text-main);
    }

    .sidebar-brand {
        display: flex;
        align-items: center;
        gap: 0.9rem;
        padding: 1rem 1rem 1.05rem;
        margin-bottom: 0.9rem;
        background: linear-gradient(135deg, rgba(8, 20, 32, 0.88) 0%, rgba(14, 35, 54, 0.68) 55%, rgba(18, 45, 72, 0.52) 100%);
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 24px;
        box-shadow: 0 18px 34px rgba(5, 16, 27, 0.24);
        backdrop-filter: blur(18px);
        position: relative;
        overflow: hidden;
        transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
    }

    .sidebar-brand::before {
        content: "";
        position: absolute;
        inset: 0;
        background:
            radial-gradient(circle at top right, rgba(110, 187, 255, 0.18), transparent 34%),
            linear-gradient(180deg, rgba(255, 255, 255, 0.06) 0%, rgba(255, 255, 255, 0) 42%);
        pointer-events: none;
    }

    .sidebar-brand:hover {
        transform: translateY(-4px);
        border-color: rgba(142, 205, 255, 0.28);
        box-shadow: 0 28px 44px rgba(7, 20, 35, 0.40);
    }

    .brand-mark {
        width: 64px;
        height: 64px;
        border-radius: 22px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: linear-gradient(160deg, rgba(126, 201, 255, 0.98) 0%, rgba(51, 107, 201, 0.98) 52%, rgba(24, 71, 156, 0.98) 100%);
        box-shadow: 0 16px 30px rgba(16, 53, 116, 0.28);
        position: relative;
        overflow: hidden;
        flex-shrink: 0;
        transition: transform 0.22s ease, box-shadow 0.22s ease;
    }

    .sidebar-brand:hover .brand-mark {
        transform: scale(1.05) rotate(-2deg);
        box-shadow: 0 24px 40px rgba(16, 53, 116, 0.42);
    }

    .brand-mark::before {
        content: "";
        position: absolute;
        inset: 0;
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.18) 0%, rgba(255, 255, 255, 0) 45%);
    }

    .brand-mark::after {
        content: "";
        position: absolute;
        inset: 8px;
        border: 1px solid rgba(255, 255, 255, 0.24);
        border-radius: 18px;
    }

    .brand-logo {
        position: relative;
        z-index: 1;
        width: 42px;
        height: 42px;
    }

    .brand-logo .logo-monogram {
        fill: none;
        stroke: rgba(247, 251, 255, 0.98);
        stroke-width: 4.6;
        stroke-linecap: round;
        stroke-linejoin: round;
    }

    .brand-logo .logo-accent {
        fill: none;
        stroke: rgba(228, 243, 255, 0.96);
        stroke-width: 3.1;
        stroke-linecap: round;
        stroke-linejoin: round;
    }

    .brand-logo .logo-dot {
        fill: rgba(247, 251, 255, 0.98);
    }

    .brand-copy {
        display: flex;
        flex-direction: column;
        min-width: 0;
    }

    .brand-name {
        font-size: 1.08rem;
        font-weight: 800;
        line-height: 1.1;
        letter-spacing: 0.02em;
        color: #eef7ff;
    }

    .brand-tag {
        margin-top: 0.2rem;
        font-size: 0.78rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #b8d4ef;
    }

    .brand-points {
        display: grid;
        gap: 0.5rem;
        margin: -0.15rem 0 1rem;
    }

    .brand-point {
        display: flex;
        align-items: center;
        gap: 0.55rem;
        padding: 0.58rem 0.72rem;
        background: rgba(255, 255, 255, 0.045);
        border: 1px solid rgba(255, 255, 255, 0.09);
        border-radius: 15px;
        font-size: 0.78rem;
        color: #dbeaf8;
    }

    .brand-point-dot {
        width: 8px;
        height: 8px;
        border-radius: 999px;
        background: linear-gradient(180deg, #8fcbff 0%, #4f9cf9 100%);
        box-shadow: 0 0 0 4px rgba(79, 156, 249, 0.12);
        flex-shrink: 0;
    }

    .report-preview-shell {
        margin-top: 0.8rem;
        padding: 0.9rem 0.95rem 0.75rem;
        background: linear-gradient(135deg, rgba(10, 24, 38, 0.78) 0%, rgba(17, 41, 63, 0.58) 100%);
        border: 1px solid rgba(255, 255, 255, 0.10);
        border-radius: 18px;
        box-shadow: 0 14px 28px rgba(5, 16, 27, 0.18);
        backdrop-filter: blur(16px);
    }

    .report-preview-kicker {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.28rem 0.62rem;
        border-radius: 999px;
        background: rgba(79, 156, 249, 0.12);
        border: 1px solid rgba(79, 156, 249, 0.22);
        color: #dff0ff;
        font-size: 0.72rem;
        letter-spacing: 0.07em;
        text-transform: uppercase;
    }

    .report-preview-title {
        margin: 0.7rem 0 0.2rem;
        font-size: 0.95rem;
        font-weight: 700;
        color: #eef7ff;
    }

    .report-preview-note {
        margin: 0;
        font-size: 0.78rem;
        line-height: 1.5;
        color: #c4d6e8;
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] {
        margin-top: 0.55rem;
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] details {
        background: rgba(255, 255, 255, 0.045);
        border: 1px solid rgba(255, 255, 255, 0.09);
        border-radius: 18px;
        overflow: hidden;
        box-shadow: 0 14px 26px rgba(5, 16, 27, 0.16);
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] summary {
        background: linear-gradient(135deg, rgba(13, 31, 48, 0.92) 0%, rgba(19, 47, 74, 0.64) 100%);
        border-radius: 18px;
        padding: 0.28rem 0.4rem;
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
        background: linear-gradient(135deg, rgba(16, 36, 56, 0.98) 0%, rgba(24, 54, 84, 0.72) 100%);
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] details[open] {
        border-color: rgba(79, 156, 249, 0.18);
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] label p {
        font-size: 0.8rem;
    }

    .module-diagrams {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 0.55rem;
        margin: 0.25rem 0 1rem;
    }

    .module-diagram {
        padding: 0.65rem 0.35rem 0.5rem;
        background: linear-gradient(135deg, rgba(15, 33, 51, 0.86) 0%, rgba(14, 45, 76, 0.52) 100%);
        border: 1px solid rgba(255, 255, 255, 0.10);
        border-radius: 18px;
        box-shadow: 0 12px 24px rgba(5, 16, 27, 0.18);
        backdrop-filter: blur(16px);
        text-align: center;
        transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease, background 0.22s ease;
    }

    .module-diagram svg {
        width: 28px;
        height: 28px;
        display: block;
        margin: 0 auto 0.45rem;
        transition: transform 0.22s ease, filter 0.22s ease;
    }

    .module-diagram span {
        display: block;
        font-size: 0.66rem;
        line-height: 1.25;
        color: #d9ebfb;
        transition: color 0.22s ease;
    }

    .module-diagram:hover {
        transform: translateY(-3px);
        background: linear-gradient(135deg, rgba(18, 38, 60, 0.92) 0%, rgba(18, 52, 83, 0.66) 100%);
        border-color: rgba(255, 255, 255, 0.16);
        box-shadow: 0 18px 30px rgba(6, 18, 31, 0.26);
    }

    .module-diagram:hover svg {
        transform: scale(1.08);
        filter: drop-shadow(0 8px 12px rgba(96, 170, 255, 0.18));
    }

    .module-diagram:hover span {
        color: #f6fbff;
    }

    .module-diagram:nth-child(1):hover {
        border-color: rgba(122, 193, 255, 0.24);
        box-shadow: 0 18px 30px rgba(26, 81, 141, 0.22);
    }

    .module-diagram:nth-child(2):hover {
        border-color: rgba(255, 187, 198, 0.22);
        box-shadow: 0 18px 30px rgba(133, 42, 68, 0.20);
    }

    .module-diagram:nth-child(3):hover {
        border-color: rgba(174, 223, 199, 0.24);
        box-shadow: 0 18px 30px rgba(28, 104, 85, 0.20);
    }

    div[role="radiogroup"] label {
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid transparent;
        border-radius: 16px;
        padding: 0.55rem 0.65rem;
        transition: transform 0.2s ease, border-color 0.2s ease, background 0.2s ease;
    }

    div[role="radiogroup"] label:hover {
        transform: translateX(4px);
        border-color: rgba(79, 156, 249, 0.28);
        background: rgba(79, 156, 249, 0.08);
    }

    div[data-testid="stVerticalBlockBorderWrapper"] {
        background: linear-gradient(135deg, rgba(12, 27, 43, 0.62) 0%, rgba(17, 41, 63, 0.42) 100%);
        border: 1px solid var(--glass-border);
        border-radius: 26px;
        backdrop-filter: blur(18px);
        box-shadow: var(--glass-shadow);
        transition: transform 0.25s ease, box-shadow 0.25s ease, border-color 0.25s ease;
    }

    div[data-testid="stVerticalBlockBorderWrapper"]:hover {
        transform: translateY(-4px);
        border-color: rgba(79, 156, 249, 0.26);
        box-shadow: 0 26px 48px rgba(0, 0, 0, 0.30);
    }

    .stTextInput > div > div > input, .stNumberInput > div > div > input {
        background: rgba(5, 15, 24, 0.74);
        color: var(--text-main);
        border-radius: 14px;
        border: 1px solid rgba(184, 198, 216, 0.22);
        transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease, background 0.2s ease;
        backdrop-filter: blur(14px);
    }

    .stTextInput > div > div > input:hover, .stNumberInput > div > div > input:hover {
        background: rgba(7, 18, 29, 0.86);
        border-color: rgba(79, 156, 249, 0.24);
        transform: translateY(-1px);
    }

    .stTextInput > div > div > input:focus, .stNumberInput > div > div > input:focus {
        border-color: rgba(79, 156, 249, 0.85);
        box-shadow: 0 0 0 1px rgba(79, 156, 249, 0.35), 0 10px 24px rgba(15, 52, 110, 0.24);
    }

    .stButton > button {
        background: linear-gradient(135deg, rgba(86, 164, 255, 0.96) 0%, rgba(31, 95, 191, 0.96) 100%);
        color: white;
        border: none;
        padding: 12px 24px;
        border-radius: 999px;
        font-weight: 700;
        letter-spacing: 0.02em;
        transition: transform 0.22s ease, box-shadow 0.22s ease, filter 0.22s ease;
        width: 100%;
        box-shadow: 0 14px 28px rgba(18, 65, 138, 0.30);
    }

    .stButton > button:hover {
        transform: translateY(-3px) scale(1.01);
        box-shadow: 0 18px 34px rgba(18, 65, 138, 0.36);
        filter: saturate(1.08);
    }

    .stButton > button:active {
        transform: translateY(-1px) scale(0.995);
    }

    [data-testid="stAlert"] {
        border-radius: 18px;
        border: 1px solid rgba(255, 255, 255, 0.10);
        background: var(--glass-strong);
        backdrop-filter: blur(14px);
    }

    [data-testid="stImage"] img {
        border-radius: 18px;
        border: 1px solid rgba(255, 255, 255, 0.12);
        box-shadow: 0 16px 30px rgba(5, 16, 27, 0.22);
    }

    hr {
        border-color: rgba(255, 255, 255, 0.10);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

try:
    diabetes_model = load_model("diabetes_model.pkl")
    heart_model = load_model("heart_model.pkl")
    liver_model = load_model("liver_model.pkl")
except FileNotFoundError:
    st.error("⚠️ System Error: Neural Models not found. Run 'python train_models.py' first.")
    st.stop()

init_session_state()

module_labels = {
    "Diabetes Detection": "🩸  Diabetes Detection",
    "Heart Health Scan": "❤️  Heart Health Scan",
    "Liver Function Test": "🧪  Liver Function Test",
}

with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-brand">
            <div class="brand-mark">
                <svg class="brand-logo" viewBox="0 0 64 64" aria-hidden="true">
                    <path class="logo-monogram" d="M17 47V17l15 19V17"></path>
                    <path class="logo-monogram" d="M39 17v30M39 31h10M49 17v30"></path>
                    <path class="logo-accent" d="M44 13v8M40 17h8"></path>
                    <circle class="logo-dot" cx="18" cy="47" r="2.6"></circle>
                </svg>
            </div>
            <div class="brand-copy">
                <div class="brand-name">NeuroHealth AI</div>
                <div class="brand-tag">Health Risk Prediction</div>
            </div>
        </div>
        <div class="brand-points">
            <div class="brand-point"><span class="brand-point-dot"></span><span>One click prediction</span></div>
            <div class="brand-point"><span class="brand-point-dot"></span><span>Input based ML analysis</span></div>
            <div class="brand-point"><span class="brand-point-dot"></span><span>Vitals driven risk scoring</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("---")
    st.markdown(
        """
        <div class="module-diagrams">
            <div class="module-diagram">
                <svg viewBox="0 0 64 64" aria-hidden="true">
                    <path d="M32 10c-8 12-16 20-16 29 0 9.4 7.2 17 16 17s16-7.6 16-17c0-9-8-17-16-29z" fill="rgba(109,184,255,0.14)" stroke="rgba(109,184,255,0.88)" stroke-width="3"/>
                    <path d="M24 36h6l3-5 4 9 3-4h4" fill="none" stroke="#f5fbff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <span>Diabetes</span>
            </div>
            <div class="module-diagram">
                <svg viewBox="0 0 64 64" aria-hidden="true">
                    <path d="M32 52c-11-7-18-14-18-24 0-7 5-12 11-12 4 0 7 2 9 5 2-3 5-5 9-5 6 0 11 5 11 12 0 10-7 17-18 24z" fill="rgba(109,184,255,0.14)" stroke="rgba(109,184,255,0.88)" stroke-width="3" stroke-linejoin="round"/>
                    <path d="M18 31h8l3-5 5 11 4-6h8" fill="none" stroke="#f5fbff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <span>Heart</span>
            </div>
            <div class="module-diagram">
                <svg viewBox="0 0 64 64" aria-hidden="true">
                    <path d="M18 21c0-5 4-9 9-9h10c11 0 17 7 17 17 0 11-7 19-18 19H27c-5 0-9-4-9-9V21z" fill="rgba(109,184,255,0.14)" stroke="rgba(109,184,255,0.88)" stroke-width="3"/>
                    <path d="M23 26h17M23 33h12M23 40h15" fill="none" stroke="#f5fbff" stroke-width="3" stroke-linecap="round"/>
                </svg>
                <span>Liver</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    selected = st.radio(
        "Select a Diagnostic Module",
        ["Diabetes Detection", "Heart Health Scan", "Liver Function Test"],
        index=0,
        format_func=lambda option: module_labels[option],
    )

    st.markdown("---")
    st.info("💡 **ML Prediction Demo**\nInput-based health risk analysis.")

    st.markdown("---")
    st.subheader("Upload Report & Auto-Fill")
    with st.expander("＋ Add Report Source", expanded=False):
        uploaded_report = st.file_uploader(
            "Choose Report From Files",
            type=["jpg", "jpeg", "png"],
            key="report_uploader",
        )
        camera_report = st.camera_input(
            "Capture Report With Mobile Camera",
            key="camera_report_input",
        )
        st.caption("Use files, gallery images, recent photos, or a fresh mobile capture from one place.")
    selected_report = camera_report if camera_report is not None else uploaded_report
    selected_source = "Mobile Camera" if camera_report is not None else "Gallery Upload"

    if selected_report is not None:
        st.markdown(
            f"""
            <div class="report-preview-shell">
                <div class="report-preview-kicker">Selected Source • {selected_source}</div>
                <div class="report-preview-title">Report Preview</div>
                <p class="report-preview-note">Keep the report flat, crop extra background, and make sure the lab values are clearly visible for faster extraction.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.image(
            selected_report.getvalue(),
            caption=f"Preview • {selected_source}",
            use_container_width=True,
        )

    if st.button("Extract Values From Report", key="extract_report_values_button"):
        report_file = selected_report
        report_source = "mobile camera" if camera_report is not None else "uploaded image"

        if report_file is None:
            st.warning("Please upload a report image or capture one from your mobile camera first.")
        else:
            try:
                with st.spinner(f"Reading {report_source} with Gemini Vision..."):
                    extracted_values = extract_report_values(report_file.getvalue())
                st.session_state["extracted_report_values"] = extracted_values
                st.success("Report values extracted successfully.")
            except Exception as exc:
                st.error(f"Unable to extract report values: {exc}")

    extracted_values = st.session_state.get("extracted_report_values", {})
    if extracted_values:
        st.caption("Extracted values")
        st.json({REPORT_LABELS[key]: value for key, value in extracted_values.items()})

        if st.button("Auto-Fill Main Fields", key="autofill_report_values_button"):
            apply_extracted_values(extracted_values)
            st.rerun()

st.markdown(
    f"""
    <div class="hero-panel">
        <div class="hero-kicker">Precision Health Dashboard</div>
        <h1 class="hero-title">{selected}</h1>
        <p class="hero-subtitle">Enter patient vitals below for instant model-based risk prediction with a cleaner glass-style interface.</p>
    </div>
    """,
    unsafe_allow_html=True,
)
st.write("")

if selected == "Diabetes Detection":
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            pregnancies = st.number_input(
                "🤰 Pregnancies",
                min_value=0,
                max_value=20,
                step=1,
                key="diabetes_pregnancies",
            )
            bmi = st.number_input(
                "⚖️ BMI Index",
                min_value=0.0,
                max_value=70.0,
                step=0.1,
                key="diabetes_bmi",
            )
        with col2:
            glucose = st.number_input(
                "🍬 Glucose Level",
                min_value=0,
                max_value=300,
                step=1,
                key="diabetes_glucose",
            )
            age = st.number_input(
                "📅 Age",
                min_value=0,
                max_value=120,
                step=1,
                key="diabetes_age",
            )
        with col3:
            bp = st.number_input(
                "💓 Blood Pressure",
                min_value=0,
                max_value=200,
                step=1,
                key="diabetes_bp",
            )

        st.write("")
        if st.button("Analyze Report"):
            with st.spinner("🤖 Analyzing input values..."):
                time.sleep(2)
                user_input = [[pregnancies, glucose, bp, bmi, age]]
                prediction = diabetes_model.predict(user_input)

                if prediction[0] == 1:
                    st.error("⚠️ **CRITICAL ALERT:** High probability of Diabetes detected.")
                    st.markdown("Recommended Action: Consult an Endocrinologist immediately.")
                else:
                    st.success("✅ **STATUS NORMAL:** No signs of Diabetes detected.")
                    st.balloons()

if selected == "Heart Health Scan":
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            age = st.number_input(
                "📅 Patient Age",
                min_value=0,
                max_value=120,
                step=1,
                key="heart_age",
            )
            heart_rate = st.number_input(
                "💓 Max Heart Rate",
                min_value=0,
                max_value=250,
                step=1,
                key="heart_rate",
            )
        with col2:
            chol = st.number_input(
                "🩸 Cholesterol (mg/dl)",
                min_value=0,
                max_value=600,
                step=1,
                key="cholesterol",
            )
            oldpeak = st.number_input(
                "📉 ST Depression",
                min_value=0.0,
                max_value=10.0,
                step=0.1,
                key="oldpeak",
            )

        st.write("")
        if st.button("Run Cardiac Prediction"):
            with st.spinner("🫀 Evaluating cardiac risk..."):
                time.sleep(2)
                user_input = [[age, chol, heart_rate, oldpeak]]
                prediction = heart_model.predict(user_input)

                if prediction[0] == 1:
                    st.error("⚠️ **CARDIAC ALERT:** Risk of Heart Disease identified.")
                    st.markdown("Recommended Action: ECG and further cardiology tests required.")
                else:
                    st.success("✅ **HEART HEALTHY:** Cardiac functions are within normal range.")
                    st.balloons()

if selected == "Liver Function Test":
    with st.container(border=True):
        col1, col2 = st.columns(2)
        with col1:
            age = st.number_input(
                "📅 Patient Age",
                min_value=0,
                max_value=120,
                step=1,
                key="liver_age",
            )
            direct_bilirubin = st.number_input(
                "🧪 Direct Bilirubin",
                min_value=0.0,
                max_value=20.0,
                step=0.1,
                key="direct_bilirubin",
            )
        with col2:
            total_bilirubin = st.number_input(
                "⚗️ Total Bilirubin",
                min_value=0.0,
                max_value=50.0,
                step=0.1,
                key="total_bilirubin",
            )
            albumin = st.number_input(
                "🧬 Albumin Level",
                min_value=1.0,
                max_value=6.0,
                step=0.1,
                key="albumin",
            )

        st.write("")
        if st.button("Analyze Liver Prediction"):
            with st.spinner("🧪 Evaluating liver indicators..."):
                time.sleep(2)
                user_input = [[age, total_bilirubin, direct_bilirubin, albumin]]
                prediction = liver_model.predict(user_input)

                if prediction[0] == 1:
                    st.error("⚠️ **LIVER ALERT:** Abnormal liver function detected.")
                else:
                    st.success("✅ **LIVER HEALTHY:** Enzymes are balanced.")
                    st.balloons()
