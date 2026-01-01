import os
import io
import difflib
import unicodedata
import html
from typing import List, Optional

import pandas as pd
import requests

from fastapi import FastAPI, Request, Depends, HTTPException, File, UploadFile
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from starlette.middleware.sessions import SessionMiddleware

from pydantic import BaseModel

from openai import OpenAI

from data_loader import (
    DATA_PATH,
    DATASETS_DIR,
    load_excel_to_tables,
    load_tables_for_dataset_id,
    load_tables_from_drive_dataset,
)

from datasets_config import DATASETS_SPREADSHEETS

client = OpenAI()

def _norm_text(s: str) -> str:
    """Normaliza texto: minúsculas, sin acentos, sin dobles espacios."""
    if s is None:
        return ""
    s = str(s).strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = " ".join(s.split())
    return s


def best_match(query: str, choices: List[str], cutoff: float = 0.72) -> Optional[str]:
    """
    Devuelve el elemento de 'choices' más parecido a 'query' (tolerante a typos).
    cutoff ~ 0.72 suele funcionar bien para nombres.
    """
    if not query or not choices:
        return None

    qn = _norm_text(query)
    # Mapa normalizado -> original
    norm_map = {}
    norm_list = []
    for c in choices:
        cn = _norm_text(c)
        if cn and cn not in norm_map:
            norm_map[cn] = c
            norm_list.append(cn)

    matches = difflib.get_close_matches(qn, norm_list, n=1, cutoff=cutoff)
    if not matches:
        return None
    return norm_map[matches[0]]


def smart_filter(df: pd.DataFrame, col: str, query: str) -> pd.DataFrame:
    """
    Filtra df por una columna:
    1) Contiene (case-insensitive, sin acentos)
    2) Si no hay resultados: usa best_match contra valores únicos y filtra exacto
    """
    if col not in df.columns:
        return df

    qn = _norm_text(query)
    if not qn:
        return df

    # 1) contiene (subcadena)
    series_norm = df[col].astype(str).map(_norm_text)
    mask_contains = series_norm.str.contains(qn, na=False)
    hit = df[mask_contains]
    if not hit.empty:
        return hit

    # 2) fuzzy contra únicos
    uniques = df[col].dropna().astype(str).unique().tolist()
    bm = best_match(query, uniques, cutoff=0.72)
    if bm:
        return df[df[col].astype(str) == bm]

    return df


ENV = os.getenv("ENV", "local").lower()
IS_PROD = ENV == "prod"



# Límites para que el contexto que se envía al modelo sea ligero
MAX_TABLES_FOR_PROMPT = 3      # máx. hojas que se describen
MAX_COLS_PER_TABLE = 6         # máx. columnas por hoja
MAX_ROWS_PER_TABLE = 2         # máx. filas de ejemplo por hoja

# ---------- CONFIGURACIÓN BÁSICA ----------

ENVIRONMENT = os.environ.get("ENVIRONMENT", "development")

app = FastAPI(
    docs_url="/docs" if ENVIRONMENT != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("APP_SECRET_KEY", "dev-secret-key"),
    session_cookie="pulso_analytics_session",
    same_site="none",
    https_only=True,
)

app.mount("/static", StaticFiles(directory="static"), name="static")

client = OpenAI()

# =========================
# Configuración de Google OAuth y acceso permitido
# =========================

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

ALLOWED_DOMAIN = os.environ.get("ALLOWED_DOMAIN", "pulsoinmobiliario.com")
ALLOWED_EMAILS_RAW = os.environ.get("ALLOWED_EMAILS", "")

ALLOWED_EMAILS = [
    email.strip().lower()
    for email in ALLOWED_EMAILS_RAW.split(",")
    if email.strip()
]

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


def is_email_allowed(email: str) -> bool:
    """
    Valida que el correo:
    1) Sea del dominio configurado (por defecto pulsoinmobiliario.com)
    2) Esté en la lista blanca ALLOWED_EMAILS (si la lista no está vacía)
    """
    email = email.lower()

    # 1) Validar dominio
    if not email.endswith(f"@{ALLOWED_DOMAIN}"):
        return False

    # 2) Validar lista blanca (si hay correos configurados)
    if ALLOWED_EMAILS and email not in ALLOWED_EMAILS:
        return False

    return True


def require_auth(request: Request):
    """
    Dependencia para proteger endpoints.
    Lanza 401 si el usuario no está autenticado.
    """
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")

# =========================
# Rutas de autenticación con Google
# =========================

@app.get("/auth/google/login")
def google_login(request: Request):
    """
    Redirige al usuario a Google para iniciar sesión.
    """
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return HTMLResponse(
            "Error de configuración: faltan GOOGLE_CLIENT_ID o GOOGLE_CLIENT_SECRET.",
            status_code=500,
        )

    redirect_uri = request.url_for("google_callback")

    from urllib.parse import urlencode

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": str(redirect_uri),
        "access_type": "online",
        "prompt": "select_account",
        "include_granted_scopes": "true",
    }

    url = f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"
    return RedirectResponse(url)


@app.get("/auth/google/callback")
def google_callback(request: Request):
    """
    Ruta a la que Google redirige después del login.
    Intercambia el 'code' por tokens y obtiene el email del usuario.
    """
    code = request.query_params.get("code")
    error = request.query_params.get("error")

    if error:
        return HTMLResponse(f"Error de Google OAuth: {error}", status_code=400)

    if not code:
        return HTMLResponse("No se recibió el código de autorización.", status_code=400)

    redirect_uri = request.url_for("google_callback")

    # 1) Intercambiar código por tokens
    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": str(redirect_uri),
        "grant_type": "authorization_code",
    }

    token_resp = requests.post(GOOGLE_TOKEN_ENDPOINT, data=data)
    if token_resp.status_code != 200:
        return HTMLResponse(
            f"Error al obtener tokens de Google: {token_resp.text}",
            status_code=500,
        )

    tokens = token_resp.json()
    access_token = tokens.get("access_token")

    if not access_token:
        return HTMLResponse(
            "No se obtuvo access_token en la respuesta de Google.",
            status_code=500,
        )

    # 2) Obtener datos del usuario
    headers = {"Authorization": f"Bearer {access_token}"}
    userinfo_resp = requests.get(GOOGLE_USERINFO_ENDPOINT, headers=headers)

    if userinfo_resp.status_code != 200:
        return HTMLResponse(
            f"Error al obtener información del usuario: {userinfo_resp.text}",
            status_code=500,
        )

    userinfo = userinfo_resp.json()
    email = userinfo.get("email")
    name = userinfo.get("name")

    if not email:
        return HTMLResponse(
            "No se obtuvo el correo electrónico del usuario.",
            status_code=500,
        )

    # 3) Validar dominio + lista blanca
    if not is_email_allowed(email):
        return HTMLResponse(
            f"Tu cuenta ({email}) no está autorizada para acceder a Pulso Analytics IA.",
            status_code=403,
        )

    # 4) Crear sesión
    request.session["authenticated"] = True
    request.session["user_email"] = email
    request.session["user_name"] = name

    # Redirigir a la página principal
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    """
    Cierra la sesión y redirige al login con Google.
    """
    request.session.clear()
    return RedirectResponse(url="/auth/google/login", status_code=303)

# =========================
# Ruta de DEBUG para probar lectura desde Google Drive
# =========================

@app.get("/debug/drive-dataset/{dataset_id}")
def debug_drive_dataset(
    dataset_id: str,
    _auth: None = Depends(require_auth),
):
    """
    Ruta de prueba para verificar que podemos leer un dataset desde Google Drive.

    - Usa load_tables_from_drive_dataset(dataset_id).
    - Regresa el listado de hojas y el número de filas/columnas de cada una.
    """
    try:
        tables = load_tables_from_drive_dataset(dataset_id)
    except Exception as e:
        # En caso de error, regresamos el mensaje para diagnosticar
        return JSONResponse(
            {"ok": False, "error": str(e)},
            status_code=500,
        )

    summary = {}
    for sheet_name, df in tables.items():
        summary[sheet_name] = {
            "rows": int(len(df)),
            "columns": int(len(df.columns)),
            "columns_names": list(df.columns.astype(str)),
        }

    return JSONResponse(
        {
            "ok": True,
            "dataset_id": dataset_id,
            "sheets": summary,
        }
    )


@app.get("/docs", response_class=HTMLResponse)
async def pulso_analytics_ui(request: Request):
    html_content = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8" />
    <title>Pulso Analytics IA</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #f5f5f5;
            color: #111827;
            display: flex;
            justify-content: center;
            padding: 24px;
        }
        .app-container {
            width: 100%;
            max-width: 900px;
            background: #ffffff;
            border-radius: 24px;
            padding: 24px 24px 16px;
            box-shadow:
                0 10px 15px -3px rgba(0,0,0,0.1),
                0 4px 6px -4px rgba(0,0,0,0.1);
            display: flex;
            flex-direction: column;
            min-height: 80vh;
        }
        .header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 16px;
        }
        .title-block {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .title {
            font-size: 1.5rem;
            font-weight: 700;
        }
        .subtitle {
            font-size: 0.875rem;
            color: #6b7280;
        }
        .logo {
            height: 40px;
            object-fit: contain;
        }
        .chat-area {
            flex: 1;
            border-radius: 16px;
            border: 1px solid #e5e7eb;
            padding: 16px;
            overflow-y: auto;
            background: #f9fafb;
            margin-bottom: 16px;
        }
        .message {
            max-width: 80%;
            padding: 10px 14px;
            border-radius: 16px;
            margin-bottom: 8px;
            font-size: 0.95rem;
            line-height: 1.4;
        }
        .message.user {
            margin-left: auto;
            background: #003C5E;
            color: #ffffff;
            border-bottom-right-radius: 4px;
        }
        .message.assistant {
            margin-right: auto;
            background: #e5e7eb;
            border-bottom-left-radius: 4px;
        }
        .input-area {
            border-top: 1px solid #e5e7eb;
            padding-top: 12px;
            display: flex;
            gap: 8px;
        }
        .input-area textarea {
            flex: 1;
            resize: none;
            border-radius: 999px;
            border: 1px solid #d1d5db;
            padding: 10px 14px;
            font-size: 0.95rem;
            outline: none;
        }
        .input-area textarea:focus {
            border-color: #003C5E;
            box-shadow: 0 0 0 1px #003C5E20;
        }
        .input-area button {
            border: none;
            border-radius: 999px;
            padding: 0 16px;
            font-size: 0.95rem;
            font-weight: 500;
            cursor: pointer;
            background: #003C5E;
            color: #ffffff;
            display: flex;
            align-items: center;
            justify-content: center;
            min-width: 90px;
        }
        .input-area button:disabled {
            opacity: 0.5;
            cursor: default;
        }
        .status {
            font-size: 0.75rem;
            color: #6b7280;
            margin-top: 4px;
        }

        /* === Estilos del selector de dataset === */
        .top-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            padding: 8px 10px;
            border-radius: 12px;
            background: #f3f4f6;
            border: 1px solid #e5e7eb;
            gap: 8px;
            flex-wrap: wrap;
        }
        .dataset-group {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .dataset-label {
            font-size: 0.85rem;
            color: #4b5563;
            font-weight: 500;
        }
        .dataset-select {
            min-width: 200px;
            padding: 6px 10px;
            border-radius: 999px;
            border: 1px solid #d1d5db;
            font-size: 0.85rem;
            outline: none;
        }
        .dataset-select:focus {
            border-color: #003C5E;
            box-shadow: 0 0 0 1px #003C5E20;
        }
        .dataset-hint {
            font-size: 0.75rem;
            color: #6b7280;
        }
        /* === FIXED CHAT LAYOUT (WhatsApp/ChatGPT style) === */
        html, body {
            height: 100%;
        }
        body {
            height: 100vh;
            overflow: hidden; /* evita scroll del body; el scroll será del chat */
        }
        .app-container {
            height: calc(100vh - 48px); /* 24px top + 24px bottom del body */
            min-height: 0;              /* permite que hijos con overflow funcionen */
        }
        .header {
            position: sticky;
            top: 0;
            background: #ffffff;
            padding-bottom: 12px;
            z-index: 20;
        }
        .top-bar {
            position: sticky;
            top: 64px;        /* debajo del header */
            z-index: 19;
        }
        .chat-area {
            min-height: 0;    /* crítico: permite scroll interno real */
            overflow-y: auto;
        }
        .input-area {
            position: sticky;
            bottom: 0;
            background: #ffffff;
            padding-bottom: 12px;
            z-index: 20;
        }        
        /* === Scroll helpers === */
        .scroll-to-bottom {
            position: fixed;
            right: 24px;
            bottom: 110px; /* arriba del input */
            background: #003C5E;
            color: #ffffff;
            border: none;
            border-radius: 999px;
            padding: 10px 14px;
            font-size: 0.85rem;
            cursor: pointer;
            box-shadow: 0 10px 15px -3px rgba(0,0,0,0.15);
            display: none; /* se activa por JS */
            z-index: 50;
        }
    </style>
</head>
<body>
    <div class="app-container">
        <header class="header">
            <div class="title-block">
                <div class="title">Pulso Analytics IA</div>
                <div class="subtitle">Asistente para análisis de datos y documentos</div>
            </div>
            <img src="/static/pulso-logo.png" alt="Pulso Inmobiliario" class="logo">
        </header>

        <div class="top-bar">
            <div class="dataset-group">
                <label for="dataset-select" class="dataset-label">Dataset:</label>
                <select id="dataset-select" class="dataset-select">
                    <option value="">(Cargando datasets...)</option>
                </select>
            </div>
            <div class="dataset-hint">
                Selecciona el archivo de datos sobre el que quieres hacer consultas.
            </div>
        </div>

        <div id="chat" class="chat-area">
            <div class="message assistant">
                Hola 👋 Soy Pulso Analytics IA. Hazme una pregunta o solicita un análisis.
            </div>
        </div>

        <button id="scroll-btn" class="scroll-to-bottom" type="button">Bajar al final</button>

        <form id="chat-form" class="input-area">
            <textarea id="user-input" rows="1" placeholder="Escribe aquí tu consulta..." required></textarea>
            <button type="submit" id="send-btn">Enviar</button>
        </form>
        <div id="status" class="status"></div>
        <div id="trace" class="status"></div>

    </div>

    <script>
        const form = document.getElementById('chat-form');
        const input = document.getElementById('user-input');
        const chat = document.getElementById('chat');
        const statusEl = document.getElementById('status');
        const traceEl = document.getElementById('trace');
        const sendBtn = document.getElementById('send-btn');
        const datasetSelect = document.getElementById('dataset-select');
        const scrollBtn = document.getElementById('scroll-btn');

        let selectedDatasetId = null;

        // === Input behavior tipo chat: auto-resize + Enter para enviar (Shift+Enter = nueva línea) ===
        function autoResizeTextarea(el) {
            el.style.height = 'auto';
            const maxHeight = 140; // px ~ 6-7 líneas
            el.style.height = Math.min(el.scrollHeight, maxHeight) + 'px';
            el.style.overflowY = (el.scrollHeight > maxHeight) ? 'auto' : 'hidden';
        }

        autoResizeTextarea(input);

        input.addEventListener('input', () => autoResizeTextarea(input));

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                form.requestSubmit(); // dispara el submit del form
            }
        });


        // 🚀 Cargar lista de datasets al inicio
        async function loadDatasets() {
            try {
                const res = await fetch('/datasets');
                const data = await res.json();

                datasetSelect.innerHTML = '';

                if (!data || data.length === 0) {
                    const opt = document.createElement('option');
                    opt.value = '';
                    opt.textContent = 'No hay datasets disponibles';
                    datasetSelect.appendChild(opt);
                    selectedDatasetId = null;
                    return;
                }

                data.forEach((ds, index) => {
                    const opt = document.createElement('option');
                    opt.value = ds.id;
                    opt.textContent = ds.filename;
                    datasetSelect.appendChild(opt);
                    if (index === 0) {
                        selectedDatasetId = ds.id;
                    }
                });

                // Trazabilidad UI (mínima)
                const selectedOpt = datasetSelect.options[datasetSelect.selectedIndex];
                traceEl.textContent = selectedOpt && selectedOpt.value
                    ? `Fuente (dataset): ${selectedOpt.textContent}`
                    : '';
                
            } catch (err) {
                datasetSelect.innerHTML = '';
                const opt = document.createElement('option');
                opt.value = '';
                opt.textContent = 'Error al cargar datasets';
                datasetSelect.appendChild(opt);
                selectedDatasetId = null;
            }
        }

        datasetSelect.addEventListener('change', () => {
            const value = datasetSelect.value;
            selectedDatasetId = value || null;

            const selectedOpt = datasetSelect.options[datasetSelect.selectedIndex];
            traceEl.textContent = selectedOpt && selectedOpt.value
                ? `Fuente (dataset): ${selectedOpt.textContent}`
                : '';
        });

        function isNearBottom() {
            const threshold = 60; // px
            return (chat.scrollHeight - chat.scrollTop - chat.clientHeight) < threshold;
        }

        function updateScrollBtn() {
            if (isNearBottom()) {
                scrollBtn.style.display = 'none';
            } else {
                scrollBtn.style.display = 'block';
            }
        }

        function scrollToBottom() {
            chat.scrollTop = chat.scrollHeight;
            updateScrollBtn();
        }

        chat.addEventListener('scroll', updateScrollBtn);

        scrollBtn.addEventListener('click', () => {
            scrollToBottom();
        });


function addMessage(text, role) {
    const div = document.createElement('div');
    div.className = 'message ' + role;

    if (role === 'assistant') {
        // Sanitización mínima sin librerías externas
        const tpl = document.createElement('template');
        tpl.innerHTML = text;

        // Eliminar scripts
        tpl.content.querySelectorAll('script').forEach(el => el.remove());

        // Eliminar handlers on* y javascript: en href/src
        tpl.content.querySelectorAll('*').forEach(el => {
            [...el.attributes].forEach(attr => {
                const name = attr.name.toLowerCase();
                const val = String(attr.value || '').toLowerCase();

                if (name.startsWith('on')) el.removeAttribute(attr.name);
                if ((name === 'href' || name === 'src') && val.startsWith('javascript:')) {
                    el.removeAttribute(attr.name);
                }
            });
        });

        div.appendChild(tpl.content);
    } else {
        // Usuario: texto plano
        div.textContent = text;
    }

    const shouldStick = isNearBottom();
    chat.appendChild(div);

    if (shouldStick) {
        scrollToBottom();
    } else {
        updateScrollBtn();
    }
}

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const question = input.value.trim();
            if (!question) return;

            addMessage(question, 'user');
            input.value = '';
            autoResizeTextarea(input);

            // ⏱️ Iniciamos cronómetro (mm:ss) en vivo
            const startTime = performance.now();
            sendBtn.disabled = true;

            let timerId = null;
            function formatElapsed(ms) {
                const totalSeconds = Math.floor(ms / 1000);
                const mm = String(Math.floor(totalSeconds / 60)).padStart(2, '0');
                const ss = String(totalSeconds % 60).padStart(2, '0');
                return `${mm}:${ss}`;
            }
            function startTimer() {
                statusEl.textContent = `Analizando información… (${formatElapsed(0)})`;
                timerId = setInterval(() => {
                    const now = performance.now();
                    statusEl.textContent = `Analizando información… (${formatElapsed(now - startTime)})`;
                }, 250);
            }
            function stopTimer(finalText) {
                if (timerId) clearInterval(timerId);
                timerId = null;
                statusEl.textContent = finalText;
            }

            startTimer();

            try {
                const payload = { query: question };
                if (selectedDatasetId) {
                    payload.dataset_id = selectedDatasetId;
                }

                const res = await fetch('/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify(payload)
                });

                const data = await res.json();
                addMessage(data.answer, 'assistant');

                // ⏱️ Tiempo final
                const endTime = performance.now();
                const final = `Tiempo de respuesta: ${formatElapsed(endTime - startTime)}`;
                stopTimer(final);
            } catch (err) {
                const endTime = performance.now();
                addMessage('Error al obtener respuesta del servidor.', 'assistant');
                stopTimer(`Error. Tiempo transcurrido: ${formatElapsed(endTime - startTime)}`);
            } finally {
                sendBtn.disabled = false;
            }
        });

        // Cargar datasets al inicio
        loadDatasets();
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    # Validación: si no hay sesión, mandar al login con Google
    if not request.session.get("authenticated"):
        return RedirectResponse(url="/auth/google/login", status_code=303)

    # Si ya está autenticado, mostrar la interfaz actual
    return await pulso_analytics_ui(request)


# ---------- CORS ----------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- ESTADO GLOBAL POR DEFECTO ----------

# Dataset por defecto (cuando no se especifica dataset_id)
tables_global: dict[str, pd.DataFrame] = {}


@app.on_event("startup")
def startup_event():
    global tables_global
    try:
        tables_global = load_excel_to_tables(DATA_PATH)
        print("✅ Tablas cargadas con éxito. Hojas disponibles:")
        for name, df in tables_global.items():
            print(f" - {name}: {len(df)} filas, {len(df.columns)} columnas")
    except Exception as e:
        print("⚠️ Error cargando tablas iniciales:", e)
        tables_global = {}


# ---------- IA (MODELO OPENAI) ----------

def call_openai(messages, model: str = "gpt-4.1-mini"):
    """
    Llama al modelo de OpenAI usando la API de chat.completions.
    'messages' es una lista de dicts con role/content, por ejemplo:
    [
        {"role": "system", "content": "Eres un analista de datos..."},
        {"role": "user", "content": "¿Qué inmueble tuvo el mayor NOI en 2025?"}
    ]
    """
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=800,
    )

    return response.choices[0].message.content.strip()


def generate_pandas_code(question: str, tables: dict[str, pd.DataFrame]) -> str:
    """
    Pide al modelo que genere código Python/pandas para responder la pregunta
    usando el diccionario 'tables', donde:
      - keys = nombres de hoja
      - values = DataFrames

    OPTIMIZADO:
    - Solo mandamos al modelo una MUESTRA pequeña:
      pocas tablas, pocas columnas y pocas filas.
    """

    # 1) Construimos descripción compacta de cada tabla
    tables_info_parts = []
    for idx, (name, df) in enumerate(tables.items()):
        if idx >= MAX_TABLES_FOR_PROMPT:
            break

        # Limitamos columnas y filas
        cols = list(df.columns[:MAX_COLS_PER_TABLE])
        df_small = df[cols].head(MAX_ROWS_PER_TABLE)

        columns_info = [f"{col} ({str(df_small[col].dtype)})" for col in cols]
        sample_rows = df_small.to_dict(orient="records")

        tables_info_parts.append(
            f"Hoja '{name}':\n"
            f"  Columnas (muestra): {columns_info}\n"
            f"  Ejemplos de filas (muestra): {sample_rows}\n"
        )

    tables_description = "\n\n".join(tables_info_parts)

    # 2) Detectamos si el usuario mencionó alguna hoja por nombre en su pregunta
    question_lower = question.lower()
    mentioned_sheets = [
        name for name in tables.keys()
        if name.lower() in question_lower
    ]

    if mentioned_sheets:
        sheets_hint = (
            "El usuario mencionó explícitamente estas hojas de cálculo: "
            f"{', '.join([repr(n) for n in mentioned_sheets])}. "
            "Debes usar PRINCIPALMENTE esas hojas en tu respuesta. "
            "En tu código, asigna primero una variable df con la hoja principal, por ejemplo:\n"
            "    df = tables['NombreHoja']\n"
            "Solo si tiene sentido, puedes combinarla con otras hojas."
        )
    else:
        sheets_hint = (
            "El usuario NO mencionó explícitamente ninguna hoja por nombre. "
            "Debes elegir la hoja o las hojas más relevantes según las columnas descritas "
            "en la sección de tablas disponibles."
        )

    system_msg = {
        "role": "system",
        "content": (
            "Eres un experto en análisis de datos con pandas. "
            "Tienes múltiples DataFrames almacenados en un diccionario llamado 'tables', "
            "donde las llaves son los nombres de las hojas de Excel y los valores son DataFrames.\n\n"
            "IMPORTANTE: Solo ves una MUESTRA de cada tabla (pocas columnas y filas) "
            "para que el contexto sea ligero, pero debes asumir que hay más datos "
            "con la misma estructura.\n\n"
            "Debes generar SOLO código Python válido para responder la pregunta del usuario.\n\n"
            "REGLAS:\n"
            "1) Usa EXCLUSIVAMENTE los datos que están en 'tables'. NO inventes datos ni valores.\n"
            "2) Si el usuario menciona explícitamente una hoja por nombre, debes usarla como fuente principal, "
            "accediendo a ella con tables['NombreHoja'].\n"
            "3) Si no se menciona ninguna hoja por nombre, elige la(s) hoja(s) más relevante(s).\n"
            "4) Accede a las tablas SIEMPRE a través de 'tables[\"NombreHoja\"]'.\n"
            "5) No modifiques las tablas originales dentro de 'tables'; si necesitas filtrar, "
            "haz copias (df_filtrado = df[...]).\n"
            "6) El resultado final debe quedar en una variable llamada 'result'.\n"
            "7) Si la combinación de filtros que pide el usuario NO existe, "
            "define 'result' como una cadena de texto explicando que no hay datos.\n"
            "7.1) Para filtros por TEXTO (por ejemplo columnas como 'Inmueble', 'Ubicación', 'Nombre', "
            "'Colaborador' u otras similares), NO uses igualdad exacta. "
            "Usa la función smart_filter(df, 'NombreColumna', 'texto_del_usuario') para permitir "
            "coincidencias parciales y tolerancia a errores de escritura.\n"
            "7.2) IMPORTANTE: smart_filter(df, 'Col', 'texto') REGRESA un DataFrame filtrado. "
            "NO lo uses dentro de df[...] (ej. NO hagas df[smart_filter(...)]. "
            "El uso correcto es: df_filtrado = smart_filter(df, 'Col', 'texto') y luego usa df_filtrado.\n"
            "7.3) Si el usuario pregunta por personas/colaboradores (por ejemplo nombres) y la(s) tabla(s) seleccionada(s) "
            "son demográficas o de gestión de personal, responde SOLO con la información disponible en esas tablas "
            "(puesto, área, fecha, antigüedad, etc.). NO menciones métricas financieras como NOI, GOP, presupuesto, rentas, etc. "
            "a menos que existan explícitamente en las columnas.\n"
            "8) NO uses ``` ni bloques de código. SOLO código Python limpio, sin comentarios ni prints."

        ),
    }

    user_msg = {
        "role": "user",
        "content": (
            "Tienes las siguientes tablas disponibles en el diccionario 'tables'. "
            "OJO: solo ves una muestra reducida de columnas y filas para cada tabla:\n\n"
            f"{tables_description}\n\n"
            f"Pregunta del usuario:\n{question}\n\n"
            f"Instrucción sobre hojas mencionadas:\n{sheets_hint}\n\n"
            "Escribe SOLO el código Python que:\n"
            "- Elija la hoja adecuada (o las adecuadas) desde 'tables'.\n"
            "- Si el usuario nombró una hoja (por ejemplo 'Demográficos'), úsala como principal.\n"
            "- Realice los filtros y cálculos necesarios.\n"
            "- Asigne el resultado final a la variable 'result'.\n"
            "No incluyas texto adicional, ni comentarios, ni prints, ni bloques ```."
        ),
    }

    code_text = call_openai([system_msg, user_msg])

    # Limpieza: quitar ```python y ``` si el modelo los incluye
    code_text = code_text.replace("```python", "")
    code_text = code_text.replace("```", "")
    code_text = code_text.strip()

    return code_text



def explain_result(question: str, code: str, result_preview: str) -> str:
    """
    Pide al modelo que explique el resultado en lenguaje natural.
    OPTIMIZADO:
    - Limita el tamaño del texto de vista previa para no mandar bloques enormes.
    """

    # 1) Acortamos el preview si es muy largo
    MAX_PREVIEW_CHARS = 1500
    if len(result_preview) > MAX_PREVIEW_CHARS:
        result_preview = result_preview[:MAX_PREVIEW_CHARS] + "\n...[texto truncado para la explicación]"

    system_msg = {
        "role": "system",
        "content": (
            "Eres un analista financiero y de negocios que explica resultados de análisis de datos "
            "en ESPAÑOL claro, breve y accionable.\n\n"
            "Reglas importantes:\n"
            "- Si mencionas NOI, se refiere SIEMPRE a 'Ingreso Neto Operativo' "
            "(Net Operating Income). NO inventes otros significados.\n"
            "- No inventes definiciones creativas para otras siglas; si no puedes "
            "inferir con claridad su significado a partir de los datos, menciona "
            "que el acrónimo no está definido en las tablas.\n"
            "- Explica el resultado de forma concreta y con enfoque de negocio.\n"
            "- Incluye una breve interpretación y, si aplica, recomendaciones."
        ),
    }

    user_msg = {
        "role": "user",
        "content": (
            f"Pregunta original del usuario:\n{question}\n\n"
            f"Código de pandas que se ejecutó sobre el diccionario 'tables':\n{code}\n\n"
            f"Resultado (vista previa en texto, puede estar truncada):\n{result_preview}\n\n"
            "Con base en esto, explica el resultado al usuario en español, usando correctamente "
            "los conceptos financieros y sin inventar significados de acrónimos."
        ),
    }

    answer = call_openai([system_msg, user_msg])
    return answer.strip()


# ---------- MODELOS ----------

class AskRequest(BaseModel):
    question: str

class AskResponse(BaseModel):
    answer: str

class DatasetInfo(BaseModel):
    id: str
    filename: str
    ext: str

class ChatRequest(BaseModel):
    query: str
    dataset_id: Optional[str] = None

from datetime import datetime

def error_card_html(title: str, bullets: List[str], trace: Optional[str] = None) -> str:
    """
    Devuelve un bloque HTML sencillo para mostrar errores en el chat (UI).
    """
    items = "".join(f"<li>{html.escape(str(b))}</li>" for b in bullets)
    trace_html = (
        f"<div style='margin-top:8px; font-size:12px; color:#6b7280;'>"
        f"{html.escape(trace)}"
        f"</div>"
        if trace else ""
    )

    return f"""
    <div style="max-width: 100%;">
      <div style="font-weight:700; font-size:1.05rem; margin-bottom:6px;">{html.escape(title)}</div>
      <ul style="margin-left:18px; line-height:1.45;">
        {items}
      </ul>
      {trace_html}
    </div>
    """.strip()


def wrap_with_trace_html(answer_html: str, *, dataset_id: str, dataset_name: str, user_email: Optional[str]) -> str:
    """
    Agrega un footer de trazabilidad a una respuesta HTML (sin modificar el contenido principal).
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    ue = user_email or "N/D"
    trace = f"Fuente: {dataset_name} | dataset_id: {dataset_id} | Usuario: {ue} | {ts}"

    return (
        f"{answer_html}"
        f"<div style='margin-top:10px; font-size:12px; color:#6b7280;'>"
        f"{html.escape(trace)}"
        f"</div>"
    )


# ---------- ENDPOINTS ----------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/datasets", response_model=List[DatasetInfo])
def list_datasets():
    """
    Lista datasets disponibles desde Google Drive (DATASETS_SPREADSHEETS).
    Se usa para poblar el selector del frontend.
    """
    items: List[DatasetInfo] = []

    for dataset_id, cfg in DATASETS_SPREADSHEETS.items():
        # Para mantener tu modelo DatasetInfo sin romper UI:
        # - id: dataset_id (ej. "noi_inmuebles")
        # - filename: nombre legible (cfg["name"])
        # - ext: "drive" (solo para identificarlo)
        items.append(
            DatasetInfo(
                id=dataset_id,
                filename=cfg.get("name", dataset_id),
                ext="drive",
            )
        )

    return items


@app.post("/upload_excel")
async def upload_excel(
    file: UploadFile = File(...),
    _auth: None = Depends(require_auth),
):
    if IS_PROD:
        raise HTTPException(
            status_code=410,
            detail="Endpoint deshabilitado. Usa datasets desde Google Drive (selector).",
        )


    """
    Sube un nuevo archivo Excel con múltiples hojas.
    Reemplaza tables_global (modo antiguo).
    """
    global tables_global
    contents = await file.read()
    tables_global = pd.read_excel(io.BytesIO(contents), sheet_name=None)

    summary = {
        name: {
            "rows": len(df),
            "columns": list(df.columns),
        }
        for name, df in tables_global.items()
    }

    return {
        "message": "Archivo cargado. Tablas actualizadas.",
        "sheets": summary,
    }


@app.post("/ask", response_model=AskResponse)
def ask(
    request: AskRequest,
    _auth: None = Depends(require_auth),
):
    if IS_PROD:
        return AskResponse(
            answer="Este endpoint ya no se usa en producción. Selecciona un dataset de Google Drive y consulta por /ask/{dataset_id}."
        )


    global tables_global
    if not tables_global:
        return AskResponse(answer="No hay datos cargados. Sube un archivo Excel primero.")

    question = request.question

    try:
        code = generate_pandas_code(question, tables_global)
    except Exception as e:
        return AskResponse(answer=f"Error generando código: {e}")

    safe_globals = {
    "pd": pd,
    "smart_filter": smart_filter,
    "best_match": best_match,
}
    safe_locals = {"tables": {name: df.copy() for name, df in tables_global.items()}}

    try:
        exec(code, safe_globals, safe_locals)
        result = safe_locals.get("result")
    except Exception as e:
        return AskResponse(
            answer=f"Error ejecutando código generado:\n{e}\n\nCódigo generado:\n{code}"
        )

    if result is None:
        return AskResponse(
            answer=f"No se generó la variable 'result'. Código generado:\n{code}"
        )

    try:
        if isinstance(result, pd.DataFrame):
            preview = result.head(10).to_dict(orient="records")
            preview_text = f"DataFrame ({len(result)} filas):\n{preview}"
        elif isinstance(result, pd.Series):
            preview = result.head(10).to_dict()
            preview_text = f"Serie ({len(result)} elementos):\n{preview}"
        else:
            preview_text = f"Resultado ({type(result).__name__}): {result}"
    except Exception:
        preview_text = repr(result)

    try:
        explanation = explain_result(question, code, preview_text)
    except Exception as e:
        explanation = (
            f"El análisis se ejecutó bien, pero hubo un error al generar la explicación: {e}\n\n"
            f"Vista previa del resultado:\n{preview_text}"
        )

    return AskResponse(answer=explanation)


@app.post("/ask/{dataset_id}", response_model=AskResponse)
def ask_on_dataset(
    dataset_id: str,
    ask: AskRequest,
    http_request: Request,
    _auth: None = Depends(require_auth),
):

    try:
        tables = load_tables_from_drive_dataset(dataset_id)
    except Exception as e:
        return AskResponse(
            answer=f"No se pudo cargar el dataset '{dataset_id}': {e}"
        )

    question = ask.question

    try:
        code = generate_pandas_code(question, tables)
    except Exception as e:
        return AskResponse(answer=f"Error generando código: {e}")

    safe_globals = {
        "pd": pd,
        "smart_filter": smart_filter,
        "best_match": best_match,
}
    safe_locals = {"tables": {name: df.copy() for name, df in tables.items()}}

    try:
        exec(code, safe_globals, safe_locals)
        result = safe_locals.get("result")
    except Exception as e:
        return AskResponse(
            answer=f"Error ejecutando código generado:\n{e}\n\nCódigo generado:\n{code}"
        )

    if result is None:
        return AskResponse(
            answer=f"No se generó la variable 'result'. Código generado:\n{code}"
        )

    try:
        if isinstance(result, pd.DataFrame):
            preview = result.head(10).to_dict(orient="records")
            preview_text = f"DataFrame ({len(result)} filas):\n{preview}"
        elif isinstance(result, pd.Series):
            preview = result.head(10).to_dict()
            preview_text = f"Serie ({len(result)} elementos):\n{preview}"
        else:
            preview_text = f"Resultado ({type(result).__name__}): {result}"
    except Exception:
        preview_text = repr(result)

    try:
        explanation = explain_result(question, code, preview_text)
    except Exception as e:
        explanation = (
            f"El análisis se ejecutó bien, pero hubo un error al generar la explicación: {e}\n\n"
            f"Vista previa del resultado:\n{preview_text}"
        )

    dataset_name = DATASETS_SPREADSHEETS.get(dataset_id, {}).get("name", dataset_id)
    user_email = http_request.session.get("user_email") if hasattr(http_request, "session") else None

    return AskResponse(
        answer=wrap_with_trace_html(
            explanation,
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            user_email=user_email,
        )
    )


@app.post("/chat", response_model=AskResponse)
def chat(
    payload: ChatRequest,
    http_request: Request,
    _auth: None = Depends(require_auth),
):
    ask_request = AskRequest(question=payload.query)

    # 1) Validación: dataset requerido
    if not payload.dataset_id:
        return AskResponse(
            answer=error_card_html(
                title="No se seleccionó un dataset",
                bullets=[
                    "Selecciona un dataset en el menú desplegable (barra superior).",
                    "Después vuelve a enviar tu consulta.",
                ],
                trace="Fuente (dataset): no seleccionado",
            )
        )

    # 2) Validación: dataset_id permitido (debe existir en DATASETS_SPREADSHEETS)
    if payload.dataset_id not in DATASETS_SPREADSHEETS:
        return AskResponse(
            answer=error_card_html(
                title="Dataset inválido",
                bullets=[
                    f"El dataset_id recibido no existe o no está autorizado: {payload.dataset_id}",
                    "Selecciona un dataset válido desde el selector.",
                ],
                trace=f"Fuente (dataset): {payload.dataset_id}",
            )
        )

    # 3) Flujo normal
    return ask_on_dataset(payload.dataset_id, ask_request, http_request=http_request)

