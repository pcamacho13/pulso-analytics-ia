"""
Configuración de datasets y documentos para Pulso Analytics IA.

Aquí definimos qué dataset_id corresponde a qué archivo en Google Drive,
y de qué tipo es (spreadsheet para Excel/Sheets, pdf para contratos, etc.).
"""

from typing import Dict, Any

# ===============================
# Datasets numéricos (Excel / Google Sheets)
# ===============================
# Clave del dict = dataset_id que usarás en la URL y en la app
# drive_file_id = ID del archivo en Google Drive

DATASETS_SPREADSHEETS: Dict[str, Dict[str, Any]] = {
    "noi_inmuebles": {
        "name": "Finanzas – noi inmuebles",
        "drive_file_id": "1evlA46rpcMJ129Dwj33Eycg64yNwoTi9",
    },
    "gestion_personal": {
        "name": "Gestión de Personal – gestion personal",
        "drive_file_id": "13hRSF7BPFbHWZ16sQgRd8ix8JGxp2JkSPirQQ3ij2bA",
    },
    "operaciones": {
        "name": "Operaciones – operaciones",
        "drive_file_id": "1uG4Z-EmrKT-KjOW5RKWZt1oCr9EgOn23yFb1-LW-D3M",
    },
}

# ===============================
# Documentos (PDFs) para consulta (contratos, convenios, etc.)
# ===============================

DATASETS_DOCUMENTS: Dict[str, Dict[str, Any]] = {
    "contrato_espamex_1412_23_0000": {
        "name": "1412-23-0000-ESPAMEX-CTO",
        "drive_file_id": "16L2ZyXT8cY27d0Z9bIBzLtlsD2evAhe_",
    },
}

DATASETS_SPREADSHEETS = {
    "test_noi_ia": {
        "name": "Finanzas – TEST NOI IA",
        "drive_file_id": "1HNAMX0wdOj-Lv5sUydk_rFp6Er5U8P4RSjCcILdOX-4",
    },
    # el resto...
}

DATASETS_SPREADSHEETS = {
    "gestion_personal": {
        "name": "Personal – gestion_personal",
        "drive_file_id": "13hRSF7BPFbHWZ16sQgRd8ix8JGxp2JkSPirQQ3ij2bA",
    },
    # el resto...
}

