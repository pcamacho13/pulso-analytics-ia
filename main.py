from fastapi import FastAPI, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pandas as pd
import io
import os
from typing import List, Optional
from openai import OpenAI
from data_loader import (
    DATA_PATH,
    DATASETS_DIR,
    load_excel_to_tables,
    load_tables_for_dataset_id,
)

client = OpenAI()

# Límites para que el contexto que se envía al modelo sea ligero
MAX_TABLES_FOR_PROMPT = 3      # máx. hojas que se describen
MAX_COLS_PER_TABLE = 6         # máx. columnas por hoja
MAX_ROWS_PER_TABLE = 2         # máx. filas de ejemplo por hoja

# ---------- CONFIGURACIÓN BÁSICA ----------

app = FastAPI(
    title="Pulso Analytics IA",
    docs_url=None,
    redoc_url=None
)

app.mount("/static", StaticFiles(directory="static"), name="static")

client = OpenAI()

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

        <form id="chat-form" class="input-area">
            <textarea id="user-input" rows="1" placeholder="Escribe aquí tu consulta..." required></textarea>
            <button type="submit" id="send-btn">Enviar</button>
        </form>
        <div id="status" class="status"></div>
    </div>

    <script>
        const form = document.getElementById('chat-form');
        const input = document.getElementById('user-input');
        const chat = document.getElementById('chat');
        const statusEl = document.getElementById('status');
        const sendBtn = document.getElementById('send-btn');
        const datasetSelect = document.getElementById('dataset-select');

        let selectedDatasetId = null;

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
        });

        function addMessage(text, role) {
            const div = document.createElement('div');
            div.className = 'message ' + role;

            if (role === 'assistant') {
                // La IA devuelve HTML (títulos, listas, etc.)
                div.innerHTML = text;
            } else {
                // El usuario se muestra como texto plano
                div.textContent = text;
            }

            chat.appendChild(div);
            chat.scrollTop = chat.scrollHeight;
        }


        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const question = input.value.trim();
            if (!question) return;

            addMessage(question, 'user');
            input.value = '';
            input.style.height = 'auto';

            // ⏱️ Iniciamos cronómetro
            const startTime = performance.now();
            statusEl.textContent = 'Generando respuesta...';
            sendBtn.disabled = true;

            try {
                const payload = { query: question };
                if (selectedDatasetId) {
                    payload.dataset_id = selectedDatasetId;
                }

                const res = await fetch('/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const data = await res.json();
                addMessage(data.answer, 'assistant');

                // ⏱️ Calculamos tiempo al terminar
                const endTime = performance.now();
                const elapsedSeconds = (endTime - startTime) / 1000;
                statusEl.textContent = `Tiempo de respuesta: ${elapsedSeconds.toFixed(1)} segundos`;
            } catch (err) {
                const endTime = performance.now();
                const elapsedSeconds = (endTime - startTime) / 1000;
                addMessage('Error al obtener respuesta del servidor.', 'assistant');
                statusEl.textContent = `Error. Tiempo transcurrido: ${elapsedSeconds.toFixed(1)} segundos`;
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


# ---------- ENDPOINTS ----------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/datasets", response_model=List[DatasetInfo])
def list_datasets():
    """
    Lista los archivos disponibles en la carpeta datasets/.
    """
    items: List[DatasetInfo] = []

    if not os.path.exists(DATASETS_DIR):
        return items

    for fname in os.listdir(DATASETS_DIR):
        path = os.path.join(DATASETS_DIR, fname)
        if not os.path.isfile(path):
            continue

        root, ext = os.path.splitext(fname)
        ext = ext.lower()

        if ext in [".xlsx", ".xls", ".csv", ".pdf", ".docx", ".doc"]:
            items.append(DatasetInfo(id=root, filename=fname, ext=ext))

    return items


@app.post("/upload_excel")
async def upload_excel(file: UploadFile = File(...)):
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
def ask(request: AskRequest):
    global tables_global
    if not tables_global:
        return AskResponse(answer="No hay datos cargados. Sube un archivo Excel primero.")

    question = request.question

    try:
        code = generate_pandas_code(question, tables_global)
    except Exception as e:
        return AskResponse(answer=f"Error generando código: {e}")

    safe_globals = {"pd": pd}
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
def ask_on_dataset(dataset_id: str, request: AskRequest):
    try:
        tables = load_tables_for_dataset_id(dataset_id)
    except Exception as e:
        return AskResponse(
            answer=f"No se pudo cargar el dataset '{dataset_id}': {e}"
        )

    question = request.question

    try:
        code = generate_pandas_code(question, tables)
    except Exception as e:
        return AskResponse(answer=f"Error generando código: {e}")

    safe_globals = {"pd": pd}
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

    return AskResponse(answer=explanation)


@app.post("/chat", response_model=AskResponse)
def chat(request: ChatRequest):
    ask_request = AskRequest(question=request.query)

    if request.dataset_id:
        respuesta = ask_on_dataset(request.dataset_id, ask_request)
    else:
        respuesta = ask(ask_request)

    return respuesta
