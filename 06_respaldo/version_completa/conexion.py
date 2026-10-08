"""
conexion.py
===========
Capa de conexión a MongoDB para la aplicación de Control de Acceso y Logística.

Responsabilidades:
    * Leer la configuración desde variables de entorno / archivo ``.env``.
    * Crear el cliente ``pymongo.MongoClient`` y verificar que el servidor responde.
    * Asegurar que existan las colecciones requeridas por la aplicación.
    * Retornar el objeto de base de datos listo para usar.

Variables de entorno (``.env``)::

    MONGO_URI=mongodb://localhost:27017
    MONGO_DB=control_acceso

Uso::

    from conexion import obtener_db
    db = obtener_db()
    db["camiones"].insert_one({"placa": "ABC-123"})

Dependencias::

    pip install pymongo python-dotenv
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import (
    ConfigurationError,
    ConnectionFailure,
    InvalidURI,
    PyMongoError,
    ServerSelectionTimeoutError,
)

logger = logging.getLogger(__name__)

#: Colecciones que la aplicación necesita que existan.
COLECCIONES_REQUERIDAS: tuple[str, ...] = (
    "camiones",
    "accesos",
    "incidentes",
    "riesgos_eticos",
    "evaluaciones_llm",
)

#: Tiempo máximo (ms) de espera para encontrar el servidor MongoDB.
TIMEOUT_SERVIDOR_MS: int = 5000

# Cliente compartido (patrón singleton simple) para reutilizar el pool de conexiones.
_cliente: Optional[MongoClient] = None
_db: Optional[Database] = None


class ErrorConexionBD(Exception):
    """Error controlado al configurar o conectar con la base de datos."""


def _leer_configuracion() -> tuple[str, str]:
    """Carga ``.env`` y retorna ``(MONGO_URI, MONGO_DB)``.

    Raises:
        ErrorConexionBD: Si alguna de las dos variables no está definida.
    """
    load_dotenv()
    uri = os.getenv("MONGO_URI", "").strip()
    nombre_db = os.getenv("MONGO_DB", "").strip()

    faltantes = [
        nombre
        for nombre, valor in (("MONGO_URI", uri), ("MONGO_DB", nombre_db))
        if not valor
    ]
    if faltantes:
        raise ErrorConexionBD(
            f"Faltan variables de entorno: {', '.join(faltantes)}. "
            "Defínelas en el archivo .env."
        )
    return uri, nombre_db


def _asegurar_colecciones(db: Database) -> None:
    """Crea las colecciones requeridas que aún no existan."""
    existentes = set(db.list_collection_names())
    for nombre in COLECCIONES_REQUERIDAS:
        if nombre not in existentes:
            db.create_collection(nombre)
            logger.info("Colección creada: %s", nombre)


def _asegurar_indices(db: Database) -> None:
    """Crea los índices útiles; un fallo (p. ej. permisos) solo se registra como aviso."""
    indices = (
        ("camiones", [("placa", 1)], {"unique": True}),
        ("accesos", [("fecha", -1)], {}),
        ("incidentes", [("fecha", -1)], {}),
        ("incidentes", [("estado", 1)], {}),
        ("evaluaciones_llm", [("fecha", -1)], {}),
    )
    for coleccion, claves, opciones in indices:
        try:
            db[coleccion].create_index(claves, **opciones)
        except PyMongoError as exc:
            logger.warning("No se pudo crear el índice %s.%s: %s", coleccion, claves, exc)


def obtener_db(forzar_reconexion: bool = False) -> Database:
    """Conecta con MongoDB y retorna el objeto de base de datos.

    Verifica la conexión con un ``ping`` y garantiza la existencia de las
    colecciones ``camiones``, ``accesos``, ``incidentes``, ``riesgos_eticos``
    y ``evaluaciones_llm``.

    Args:
        forzar_reconexion: Si es ``True`` descarta la conexión en caché y crea una nueva.

    Returns:
        Objeto ``pymongo.database.Database`` listo para usarse.

    Raises:
        ErrorConexionBD: Si la configuración es inválida o no se puede conectar.
    """
    global _cliente, _db

    if _db is not None and not forzar_reconexion:
        return _db

    if forzar_reconexion:
        cerrar_conexion()

    uri, nombre_db = _leer_configuracion()

    cliente: Optional[MongoClient] = None
    try:
        cliente = MongoClient(uri, serverSelectionTimeoutMS=TIMEOUT_SERVIDOR_MS)
        cliente.admin.command("ping")  # Fuerza la selección de servidor ahora.
        db = cliente[nombre_db]
        _asegurar_colecciones(db)
        _asegurar_indices(db)
    except (InvalidURI, ConfigurationError) as exc:
        if cliente is not None:
            cliente.close()
        raise ErrorConexionBD(f"MONGO_URI inválida o mal configurada: {exc}") from exc
    except (ServerSelectionTimeoutError, ConnectionFailure) as exc:
        if cliente is not None:
            cliente.close()
        raise ErrorConexionBD(
            f"No se pudo conectar a MongoDB en {TIMEOUT_SERVIDOR_MS} ms. "
            f"¿Está el servicio activo? Detalle: {exc}"
        ) from exc
    except PyMongoError as exc:
        if cliente is not None:
            cliente.close()
        raise ErrorConexionBD(f"Error de MongoDB: {exc}") from exc

    _cliente, _db = cliente, db
    logger.info("Conectado a MongoDB, base de datos '%s'.", nombre_db)
    return _db


def cerrar_conexion() -> None:
    """Cierra el cliente compartido (si existe) y limpia la caché."""
    global _cliente, _db
    if _cliente is not None:
        _cliente.close()
    _cliente, _db = None, None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        base = obtener_db()
        print(f"Conexión OK. Base de datos: {base.name}")
        print("Colecciones:", sorted(base.list_collection_names()))
    except ErrorConexionBD as error:
        print(f"[ERROR] {error}")
        raise SystemExit(1)
    finally:
        cerrar_conexion()
