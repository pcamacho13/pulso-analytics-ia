"""
Configuración de datasets y documentos para Pulso Analytics IA.

Aquí definimos qué dataset_id corresponde a qué archivo en Google Drive,
y de qué tipo es (spreadsheet para Excel/Sheets, pdf para contratos, etc.).
"""

from typing import Dict, Any

# ===============================
# Datasets numéricos (Excel / Google Sheets)
# ===============================

DATASETS_SPREADSHEETS: Dict[str, Dict[str, Any]] = {
    # Nota: este file_id actualmente te da 404. Déjalo solo si ya confirmaste que es el ID correcto.
    "noi_inmuebles": {
        "name": "Finanzas – NOI Inmuebles (Excel Drive)",
        "drive_file_id": "1evlA46rpcMJ129Dwj33Eycg64yNwoTi9",
    },

    # Este ya comprobaste que funciona
    "test_noi_ia": {
        "name": "Finanzas – TEST NOI IA",
        "drive_file_id": "1HNAMX0wdOj-Lv5sUydk_rFp6Er5U8P4RSjCcILdOX-4",
    },

    # Este debería funcionar si el file_id es correcto y está en la Shared Drive
    "gestion_personal": {
        "name": "Gestión de Personal – Operación Inmuebles",
        "drive_file_id": "13hRSF7BPFbHWZ16sQgRd8ix8JGxp2JkSPirQQ3ij2bA",
    },

    # Este debería funcionar si el file_id es correcto y está en la Shared Drive
    "operaciones": {
        "name": "Operaciones – Dashboard",
        "drive_file_id": "1uG4Z-EmrKT-KjOW5RKWZt1oCr9EgOn23yFb1-LW-D3M",
    },
}

# ===============================
# Documentos (PDFs) para consulta
# ===============================

DATASETS_DOCUMENTS: Dict[str, Dict[str, Any]] = {
    "contrato_espamex_1412_23_0000": {
        "name": "1412-23-0000-ESPAMEX-CTO",
        "drive_file_id": "16L2ZyXT8cY27d0Z9bIBzLtlsD2evAhe_",
    },
}

