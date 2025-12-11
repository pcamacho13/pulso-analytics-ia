"""
Configuración de datasets y documentos para Pulso Analytics IA.

Aquí definimos qué dataset_id corresponde a qué archivo en Google Drive,
y de qué tipo es (spreadsheet para Excel/Sheets, pdf para contratos, etc.).

Tú irás rellenando los file_id con los valores reales de tus archivos en Drive.
"""

from typing import Dict, Any

# Datasets numéricos (Excel / Google Sheets)
DATASETS_SPREADSHEETS: Dict[str, Dict[str, Any]] = {
    # Ejemplo (ajusta nombres e IDs):
    # "noi_inmuebles": {
    #     "name": "Finanzas – NOI Inmuebles",
    #     "drive_file_id": "1evlA46rpcMJ129Dwj33Eycg64yNwoTi9",
    # },
}

# Documentos (PDFs) para consulta (contratos, convenios, etc.)
DATASETS_DOCUMENTS: Dict[str, Dict[str, Any]] = {
    # Ejemplo (ajusta nombres e IDs):
    # "1412-23-0000-ESPAMEX-CTO": {
    #     "name": "1412-23-0000-ESPAMEX-CTO",
    #     "drive_file_id": "16L2ZyXT8cY27d0Z9bIBzLtlsD2evAhe_",
    # },
}

# Datasets numéricos (Excel / Google Sheets)
DATASETS_SPREADSHEETS: Dict[str, Dict[str, Any]] = {
    # Ejemplo (ajusta nombres e IDs):
    # "Copia de Gestión Personal Vertical Operación Inmuebles": {
    #     "name": "Gestión de Personal – Copia de Gestión Personal Vertical Operación Inmuebles",
    #     "drive_file_id": "13hRSF7BPFbHWZ16sQgRd8ix8JGxp2JkSPirQQ3ij2bA",
    # },
}

# Datasets numéricos (Excel / Google Sheets)
DATASETS_SPREADSHEETS: Dict[str, Dict[str, Any]] = {
    # Ejemplo (ajusta nombres e IDs):
    # "Copia de 1. Dashboard Pulso Operaciones": {
    #     "name": "Operaciones – Copia de 1. Dashboard Pulso Operaciones",
    #     "drive_file_id": "1uG4Z-EmrKT-KjOW5RKWZt1oCr9EgOn23yFb1-LW-D3M",
    # },
}


