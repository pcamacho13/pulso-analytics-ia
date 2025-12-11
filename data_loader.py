import os
import pandas as pd

from gdrive_client import download_spreadsheet_as_excel
from datasets_config import DATASETS_SPREADSHEETS

# Carpeta donde viven los datasets
DATASETS_DIR = "datasets"

# Archivo Excel por defecto (para /ask simple)
DATA_PATH = os.path.join(DATASETS_DIR, "ventas_ejemplo.xlsx")


def load_excel_to_tables(path: str) -> dict[str, pd.DataFrame]:
    """
    Carga TODAS las hojas de un Excel en un diccionario:
    {
        "NombreHoja1": DataFrame1,
        "NombreHoja2": DataFrame2,
        ...
    }
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"No se encontró el archivo: {path}")
    dfs = pd.read_excel(path, sheet_name=None)  # todas las hojas
    return dfs


def load_tables_for_dataset_id(dataset_id: str) -> dict[str, pd.DataFrame]:
    """
    Dado un dataset_id (por ejemplo 'ventas_ejemplo'),
    busca un archivo con ese nombre en la carpeta datasets/
    con extensión .xlsx, .xls o .csv y lo carga como tablas.

    Retorna un dict: {nombre_hoja: DataFrame}
    """
    if not os.path.exists(DATASETS_DIR):
        raise FileNotFoundError(f"No existe el directorio de datasets: {DATASETS_DIR}")

    selected_path = None
    selected_ext = None

    for fname in os.listdir(DATASETS_DIR):
        path = os.path.join(DATASETS_DIR, fname)
        if not os.path.isfile(path):
            continue

        root, ext = os.path.splitext(fname)
        ext = ext.lower()

        if root == dataset_id and ext in [".xlsx", ".xls", ".csv"]:
            selected_path = path
            selected_ext = ext
            break

    if not selected_path:
        raise FileNotFoundError(
            f"No se encontró ningún archivo soportado para el dataset_id '{dataset_id}'. "
            "Asegúrate de que el archivo exista en la carpeta 'datasets' y tenga extensión .xlsx, .xls o .csv."
        )

    # Si es Excel con múltiples hojas
    if selected_ext in [".xlsx", ".xls"]:
        tables = pd.read_excel(selected_path, sheet_name=None)
        return tables

    # Si es CSV, lo tratamos como una sola hoja llamada 'Hoja1'
    if selected_ext == ".csv":
        df = pd.read_csv(selected_path)
        return {"Hoja1": df}

    # Este punto no debería alcanzarse
    raise ValueError(f"Extensión de archivo no soportada: {selected_ext}")
    
    def load_tables_from_drive_dataset(dataset_id: str) -> dict:
    """
    Carga un dataset (Excel o Google Sheets) desde Google Drive, usando DATASETS_SPREADSHEETS.

    - dataset_id: clave definida en DATASETS_SPREADSHEETS (por ejemplo, "core_mxn").
    - Usa download_spreadsheet_as_excel para obtener un archivo Excel en memoria.
    - Luego reutiliza pandas.read_excel para convertirlo en tablas (una por hoja).
    """
    if dataset_id not in DATASETS_SPREADSHEETS:
        raise ValueError(f"Dataset '{dataset_id}' no está configurado en DATASETS_SPREADSHEETS.")

    dataset_config = DATASETS_SPREADSHEETS[dataset_id]
    file_id = dataset_config.get("drive_file_id")

    if not file_id:
        raise ValueError(f"Dataset '{dataset_id}' no tiene drive_file_id configurado.")

    # Descargar el archivo (Google Sheet o Excel) como .xlsx en memoria
    excel_bytes_io = download_spreadsheet_as_excel(file_id)

    # Leer todas las hojas del Excel en un dict de DataFrames
    # sheet_name=None hace que pandas devuelva {nombre_hoja: DataFrame}
    xls = pd.read_excel(excel_bytes_io, sheet_name=None)

    # Si tu función load_excel_to_tables hace más cosas (limpieza, normalización),
    # podrías reutilizarla aquí. Por ahora, devolvemos el dict tal cual.
    tables = {}
    for sheet_name, df in xls.items():
        tables[sheet_name] = df

    return tables

