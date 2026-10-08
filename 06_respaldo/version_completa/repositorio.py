"""
repositorio.py
==============
Capa de acceso a datos: operaciones CRUD y agregaciones sobre MongoDB.

Colecciones y esquemas (todos los campos de fecha son ``datetime``):

``camiones``::

    {placa (única), camion_id, empresa, autorizacion: bool,
     certificacion_conductor: {conductor, vigencia: datetime},
     fecha_registro, ultimo_acceso}

``accesos`` (bitácora)::

    {placa, camion_id, operador, fecha,
     P, S, Q, R, A, E,                      # premisas y resultados (bool)
     vigencia_certificacion, hora_ingreso,
     reglas_aplicadas: [str], explicacion: [str], decision}

``incidentes``::

    {correo, clasificacion: {categoria, prioridad, origen, requiere_revision_humana},
     datos_extraidos: {entidades: [str], resumen}, estado: nuevo|en_atencion|cerrado,
     fecha, historial: [{fecha, evento, detalle}]}

``evaluaciones_llm``::

    {tipo: clasificacion|rag, prompt, respuesta, modelo, latencia_ms,
     coincide_con_reglas: bool|None, valido, error, fecha}

(``riesgos_eticos`` se gestiona en ``riesgos_eticos.py``.)

Todas las funciones reciben el objeto ``Database`` y lanzan ``ErrorRepositorio`` ante
fallos de MongoDB, ``ValueError`` ante datos inválidos.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time
from typing import Any, Optional

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError, PyMongoError

logger = logging.getLogger(__name__)

ESTADOS_INCIDENTE: tuple[str, ...] = ("nuevo", "en_atencion", "cerrado")
ESTADOS_ABIERTOS: tuple[str, ...] = ("nuevo", "en_atencion")


class ErrorRepositorio(Exception):
    """Fallo de acceso a datos (conexión, permisos, registro inexistente...)."""


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def _oid(valor: Any) -> ObjectId:
    try:
        return ObjectId(str(valor))
    except (InvalidId, TypeError):
        raise ErrorRepositorio("Identificador de registro inválido.") from None


def rango_fechas(desde: Optional[date], hasta: Optional[date]) -> dict[str, datetime]:
    """Construye el filtro ``{"$gte", "$lte"}`` para un campo fecha (límites inclusivos)."""
    filtro: dict[str, datetime] = {}
    if desde:
        filtro["$gte"] = datetime.combine(desde, time.min)
    if hasta:
        filtro["$lte"] = datetime.combine(hasta, time.max)
    return filtro


def _filtro_fecha(desde: Optional[date], hasta: Optional[date], campo: str = "fecha") -> dict[str, Any]:
    rango = rango_fechas(desde, hasta)
    return {campo: rango} if rango else {}


def _envolver(accion: str, exc: Exception) -> ErrorRepositorio:
    logger.error("%s: %s", accion, exc)
    return ErrorRepositorio(f"{accion}: {exc}")


# --------------------------------------------------------------------------- #
# Camiones
# --------------------------------------------------------------------------- #
def validar_camion(datos: dict[str, Any]) -> dict[str, Any]:
    """Valida y normaliza los datos de un camión.

    Raises:
        ValueError: Con un mensaje claro si falta o es inválido algún campo.
    """
    placa = str(datos.get("placa", "")).strip().upper()
    if not placa:
        raise ValueError("La placa es obligatoria.")
    camion_id = str(datos.get("camion_id", "")).strip().upper()
    if not camion_id:
        raise ValueError("El ID del camión es obligatorio.")
    empresa = str(datos.get("empresa", "")).strip()
    if not empresa:
        raise ValueError("La empresa es obligatoria.")
    conductor = str(datos.get("conductor", "")).strip()
    vigencia = datos.get("vigencia")
    if isinstance(vigencia, date) and not isinstance(vigencia, datetime):
        vigencia = datetime.combine(vigencia, time.min)
    if vigencia is not None and not isinstance(vigencia, datetime):
        raise ValueError("La vigencia de la certificación no es una fecha válida.")
    return {
        "placa": placa,
        "camion_id": camion_id,
        "empresa": empresa,
        "autorizacion": bool(datos.get("autorizacion", False)),
        "certificacion_conductor": {"conductor": conductor, "vigencia": vigencia},
    }


def crear_camion(db: Database, datos: dict[str, Any]) -> str:
    """Inserta un camión. Retorna su id.

    Raises:
        ValueError: Datos inválidos. ErrorRepositorio: placa duplicada o fallo de MongoDB.
    """
    doc = validar_camion(datos)
    doc["fecha_registro"] = datetime.now()
    try:
        return str(db["camiones"].insert_one(doc).inserted_id)
    except DuplicateKeyError:
        raise ErrorRepositorio(f"Ya existe un camión con la placa {doc['placa']}.") from None
    except PyMongoError as exc:
        raise _envolver("No se pudo crear el camión", exc) from exc


def actualizar_camion(db: Database, camion_id: str, datos: dict[str, Any]) -> None:
    """Actualiza un camión por id.

    Raises:
        ValueError: Datos inválidos. ErrorRepositorio: no existe, placa duplicada o fallo.
    """
    doc = validar_camion(datos)
    try:
        res = db["camiones"].update_one({"_id": _oid(camion_id)}, {"$set": doc})
    except DuplicateKeyError:
        raise ErrorRepositorio(f"Ya existe otro camión con la placa {doc['placa']}.") from None
    except PyMongoError as exc:
        raise _envolver("No se pudo actualizar el camión", exc) from exc
    if res.matched_count == 0:
        raise ErrorRepositorio("El camión ya no existe.")


def eliminar_camion(db: Database, camion_id: str) -> None:
    """Elimina un camión por id (sus accesos históricos se conservan)."""
    try:
        res = db["camiones"].delete_one({"_id": _oid(camion_id)})
    except PyMongoError as exc:
        raise _envolver("No se pudo eliminar el camión", exc) from exc
    if res.deleted_count == 0:
        raise ErrorRepositorio("El camión ya no existe.")


def listar_camiones(db: Database, texto: str = "") -> list[dict[str, Any]]:
    """Lista camiones, opcionalmente filtrando por placa, ID o empresa (subcadena)."""
    filtro: dict[str, Any] = {}
    if texto.strip():
        patron = {"$regex": re.escape(texto.strip()), "$options": "i"}
        filtro = {"$or": [{"placa": patron}, {"camion_id": patron}, {"empresa": patron}]}
    try:
        return list(db["camiones"].find(filtro).sort("placa", 1))
    except PyMongoError as exc:
        raise _envolver("No se pudieron listar los camiones", exc) from exc


def buscar_camion(db: Database, placa_o_id: str) -> Optional[dict[str, Any]]:
    """Busca un camión por placa o por ``camion_id`` (sin distinguir mayúsculas)."""
    clave = placa_o_id.strip().upper()
    try:
        return db["camiones"].find_one({"$or": [{"placa": clave}, {"camion_id": clave}]})
    except PyMongoError as exc:
        raise _envolver("No se pudo buscar el camión", exc) from exc


# --------------------------------------------------------------------------- #
# Accesos
# --------------------------------------------------------------------------- #
def registrar_acceso(
    db: Database,
    *,
    placa: str,
    camion_id: str,
    operador: str,
    premisas: dict[str, bool],
    resultado: dict[str, Any],
    vigencia: Optional[date],
    hora_ingreso: str,
    fecha: Optional[datetime] = None,
    extra: Optional[dict[str, Any]] = None,
) -> str:
    """Guarda una decisión de acceso en la bitácora y actualiza ``ultimo_acceso`` del camión.

    Args:
        premisas: ``{"P":..,"Q":..,"R":..,"S":..}``.
        resultado: Diccionario devuelto por ``motor_reglas.evaluar_acceso``.
        extra: Campos adicionales (p. ej. ``{"demo": True}``).

    Returns:
        Id del acceso insertado.
    """
    fecha = fecha or datetime.now()
    doc = {
        "placa": placa.strip().upper(),
        "camion_id": camion_id.strip().upper(),
        "operador": operador,
        "fecha": fecha,
        "P": bool(premisas["P"]), "Q": bool(premisas["Q"]),
        "R": bool(premisas["R"]), "S": bool(premisas["S"]),
        "A": bool(resultado["A"]), "E": bool(resultado["E"]),
        "decision": "AUTORIZADO" if resultado["A"] else "DENEGADO",
        "vigencia_certificacion": datetime.combine(vigencia, time.min) if vigencia else None,
        "hora_ingreso": hora_ingreso,
        "reglas_aplicadas": list(resultado["reglas_aplicadas"]),
        "explicacion": list(resultado["explicacion"]),
    }
    if extra:
        doc.update(extra)
    try:
        acceso_id = db["accesos"].insert_one(doc).inserted_id
        db["camiones"].update_one({"placa": doc["placa"]}, {"$set": {"ultimo_acceso": fecha}})
        return str(acceso_id)
    except PyMongoError as exc:
        raise _envolver("No se pudo guardar el acceso", exc) from exc


def listar_accesos(
    db: Database, desde: Optional[date] = None, hasta: Optional[date] = None,
    placa: str = "", limite: int = 200,
) -> list[dict[str, Any]]:
    """Lista accesos recientes (más nuevos primero) con filtros opcionales."""
    filtro = _filtro_fecha(desde, hasta)
    if placa.strip():
        filtro["placa"] = {"$regex": re.escape(placa.strip().upper())}
    try:
        return list(db["accesos"].find(filtro).sort("fecha", -1).limit(limite))
    except PyMongoError as exc:
        raise _envolver("No se pudieron listar los accesos", exc) from exc


def eliminar_acceso(db: Database, acceso_id: str) -> None:
    """Elimina un registro de la bitácora."""
    try:
        res = db["accesos"].delete_one({"_id": _oid(acceso_id)})
    except PyMongoError as exc:
        raise _envolver("No se pudo eliminar el acceso", exc) from exc
    if res.deleted_count == 0:
        raise ErrorRepositorio("El registro de acceso ya no existe.")


# --------------------------------------------------------------------------- #
# Incidentes
# --------------------------------------------------------------------------- #
def _evento(evento: str, detalle: str = "") -> dict[str, Any]:
    return {"fecha": datetime.now(), "evento": evento, "detalle": detalle}


def _validar_clasificacion(clasificacion: dict[str, Any], datos: dict[str, Any]) -> None:
    from clasificador_hibrido import CATEGORIAS_VALIDAS, PRIORIDADES_VALIDAS
    if clasificacion.get("categoria") not in CATEGORIAS_VALIDAS:
        raise ValueError(f"La categoría debe ser una de: {', '.join(CATEGORIAS_VALIDAS)}.")
    if clasificacion.get("prioridad") not in PRIORIDADES_VALIDAS:
        raise ValueError(f"La prioridad debe ser una de: {', '.join(PRIORIDADES_VALIDAS)}.")
    if not str(datos.get("resumen", "")).strip():
        raise ValueError("El resumen no puede estar vacío.")


def crear_incidente(
    db: Database, *, correo: str, clasificacion: dict[str, Any], datos_extraidos: dict[str, Any],
    estado: str = "nuevo", fecha: Optional[datetime] = None, extra: Optional[dict[str, Any]] = None,
) -> str:
    """Inserta un incidente con su primer evento de historial. Retorna su id.

    Raises:
        ValueError: Si la clasificación o el estado son inválidos o el correo está vacío.
    """
    if not correo.strip():
        raise ValueError("El correo original no puede estar vacío.")
    if estado not in ESTADOS_INCIDENTE:
        raise ValueError(f"Estado inválido: {estado}.")
    _validar_clasificacion(clasificacion, datos_extraidos)
    fecha = fecha or datetime.now()
    doc = {
        "correo": correo.strip(),
        "clasificacion": clasificacion,
        "datos_extraidos": datos_extraidos,
        "estado": estado,
        "fecha": fecha,
        "historial": [{"fecha": fecha, "evento": "creado",
                       "detalle": f"Origen: {clasificacion.get('origen', 'manual')}"}],
    }
    if extra:
        doc.update(extra)
    try:
        return str(db["incidentes"].insert_one(doc).inserted_id)
    except PyMongoError as exc:
        raise _envolver("No se pudo guardar el incidente", exc) from exc


def actualizar_incidente(
    db: Database, incidente_id: str, *, clasificacion: dict[str, Any],
    datos_extraidos: dict[str, Any], estado: str,
) -> None:
    """Edita la clasificación, los datos extraídos y el estado, registrando el cambio en el historial.

    Raises:
        ValueError: Datos inválidos. ErrorRepositorio: no existe o fallo de MongoDB.
    """
    if estado not in ESTADOS_INCIDENTE:
        raise ValueError(f"Estado inválido: {estado}.")
    _validar_clasificacion(clasificacion, datos_extraidos)
    try:
        previo = db["incidentes"].find_one({"_id": _oid(incidente_id)})
        if previo is None:
            raise ErrorRepositorio("El incidente ya no existe.")
        eventos = [_evento("editado", "Clasificación/datos modificados manualmente")]
        if previo.get("estado") != estado:
            eventos.append(_evento("estado", f"{previo.get('estado')} -> {estado}"))
        db["incidentes"].update_one(
            {"_id": previo["_id"]},
            {"$set": {"clasificacion": clasificacion, "datos_extraidos": datos_extraidos, "estado": estado},
             "$push": {"historial": {"$each": eventos}}},
        )
    except PyMongoError as exc:
        raise _envolver("No se pudo actualizar el incidente", exc) from exc


def cambiar_estado_incidente(db: Database, incidente_id: str, estado: str) -> None:
    """Cambia solo el estado de un incidente y lo anota en el historial."""
    if estado not in ESTADOS_INCIDENTE:
        raise ValueError(f"Estado inválido: {estado}.")
    try:
        previo = db["incidentes"].find_one({"_id": _oid(incidente_id)}, {"estado": 1})
        if previo is None:
            raise ErrorRepositorio("El incidente ya no existe.")
        db["incidentes"].update_one(
            {"_id": previo["_id"]},
            {"$set": {"estado": estado},
             "$push": {"historial": _evento("estado", f"{previo.get('estado')} -> {estado}")}},
        )
    except PyMongoError as exc:
        raise _envolver("No se pudo cambiar el estado", exc) from exc


def eliminar_incidente(db: Database, incidente_id: str) -> None:
    """Elimina un incidente."""
    try:
        res = db["incidentes"].delete_one({"_id": _oid(incidente_id)})
    except PyMongoError as exc:
        raise _envolver("No se pudo eliminar el incidente", exc) from exc
    if res.deleted_count == 0:
        raise ErrorRepositorio("El incidente ya no existe.")


def listar_incidentes(
    db: Database, estado: str = "", desde: Optional[date] = None, hasta: Optional[date] = None,
    limite: int = 300,
) -> list[dict[str, Any]]:
    """Lista incidentes (más nuevos primero), filtrando por estado y rango de fechas."""
    filtro = _filtro_fecha(desde, hasta)
    if estado:
        filtro["estado"] = estado
    try:
        return list(db["incidentes"].find(filtro).sort("fecha", -1).limit(limite))
    except PyMongoError as exc:
        raise _envolver("No se pudieron listar los incidentes", exc) from exc


def incidentes_por_categoria_semana(
    db: Database, desde: Optional[date] = None, hasta: Optional[date] = None,
) -> list[dict[str, Any]]:
    """Agregación: número de incidentes por categoría y semana ISO.

    Returns:
        Lista ordenada de ``{"semana": "2026-W41", "categoria": "Seguridad", "total": 3}``.
    """
    pipeline: list[dict[str, Any]] = []
    filtro = _filtro_fecha(desde, hasta)
    if filtro:
        pipeline.append({"$match": filtro})
    pipeline += [
        {"$group": {
            "_id": {
                "semana": {"$dateToString": {"format": "%G-W%V", "date": "$fecha"}},
                "categoria": "$clasificacion.categoria",
            },
            "total": {"$sum": 1},
        }},
        {"$sort": {"_id.semana": 1, "_id.categoria": 1}},
        {"$project": {"_id": 0, "semana": "$_id.semana", "categoria": "$_id.categoria", "total": 1}},
    ]
    try:
        return list(db["incidentes"].aggregate(pipeline))
    except PyMongoError as exc:
        raise _envolver("No se pudo calcular la agregación de incidentes", exc) from exc


# --------------------------------------------------------------------------- #
# Evaluaciones del LLM
# --------------------------------------------------------------------------- #
def registrar_evaluacion_llm(
    db: Database, *, tipo: str, prompt: str, respuesta: str, modelo: str, latencia_ms: float,
    coincide_con_reglas: Optional[bool], error: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> str:
    """Guarda una llamada al LLM en ``evaluaciones_llm``. Retorna su id."""
    doc = {
        "tipo": tipo, "prompt": prompt, "respuesta": respuesta, "modelo": modelo,
        "latencia_ms": round(float(latencia_ms), 1),
        "coincide_con_reglas": coincide_con_reglas,
        "valido": error is None, "error": error, "fecha": datetime.now(),
    }
    if extra:
        doc.update(extra)
    try:
        return str(db["evaluaciones_llm"].insert_one(doc).inserted_id)
    except PyMongoError as exc:
        raise _envolver("No se pudo registrar la evaluación del LLM", exc) from exc


def registrar_clasificacion(db: Database, resultado: Any) -> int:
    """Registra en ``evaluaciones_llm`` cada intento al LLM de un ``ResultadoClasificacion``.

    ``coincide_con_reglas`` solo se informa para el intento que produjo un resultado válido.

    Returns:
        Número de registros guardados.
    """
    for intento in resultado.intentos:
        registrar_evaluacion_llm(
            db, tipo="clasificacion", prompt=intento.prompt, respuesta=intento.respuesta,
            modelo=intento.modelo, latencia_ms=intento.latencia_ms,
            coincide_con_reglas=resultado.coincide_con_reglas if intento.valido else None,
            error=intento.error,
        )
    return len(resultado.intentos)


def listar_evaluaciones(
    db: Database, desde: Optional[date] = None, hasta: Optional[date] = None, limite: int = 500,
) -> list[dict[str, Any]]:
    """Lista evaluaciones del LLM (más nuevas primero)."""
    try:
        return list(db["evaluaciones_llm"].find(_filtro_fecha(desde, hasta)).sort("fecha", -1).limit(limite))
    except PyMongoError as exc:
        raise _envolver("No se pudieron listar las evaluaciones", exc) from exc


# --------------------------------------------------------------------------- #
# Panel de control
# --------------------------------------------------------------------------- #
def estadisticas_panel(
    db: Database, desde: Optional[date] = None, hasta: Optional[date] = None,
    umbral_alto: int = 15,
) -> dict[str, Any]:
    """Indicadores del panel de control en el rango de fechas dado.

    Returns:
        ``camiones_atendidos``, ``accesos_total``, ``accesos_autorizados``,
        ``accesos_denegados``, ``inspecciones``, ``incidentes_abiertos``,
        ``incidentes_total``, ``riesgos_criticos``, ``riesgos_criticos_residuales``,
        ``llm_llamadas`` y ``llm_latencia_media_ms``.
    """
    filtro = _filtro_fecha(desde, hasta)
    try:
        accesos = db["accesos"]
        stats: dict[str, Any] = {
            "camiones_atendidos": len(accesos.distinct("placa", filtro)),
            "accesos_total": accesos.count_documents(filtro),
            "accesos_autorizados": accesos.count_documents({**filtro, "A": True}),
            "accesos_denegados": accesos.count_documents({**filtro, "A": False}),
            "inspecciones": accesos.count_documents({**filtro, "E": True}),
            "incidentes_total": db["incidentes"].count_documents(filtro),
            "incidentes_abiertos": db["incidentes"].count_documents(
                {**filtro, "estado": {"$in": list(ESTADOS_ABIERTOS)}}),
        }
        criticos = residuales = 0
        for r in db["riesgos_eticos"].find({}, {"probabilidad": 1, "impacto": 1,
                                                "probabilidad_residual": 1, "impacto_residual": 1}):
            p, i = r.get("probabilidad", 0), r.get("impacto", 0)
            if p * i >= umbral_alto:
                criticos += 1
            if r.get("probabilidad_residual", p) * r.get("impacto_residual", i) >= umbral_alto:
                residuales += 1
        stats["riesgos_criticos"], stats["riesgos_criticos_residuales"] = criticos, residuales

        resumen = list(db["evaluaciones_llm"].aggregate([
            *([{"$match": _filtro_fecha(desde, hasta)}] if filtro else []),
            {"$group": {"_id": None, "n": {"$sum": 1}, "lat": {"$avg": "$latencia_ms"}}},
        ]))
        stats["llm_llamadas"] = resumen[0]["n"] if resumen else 0
        stats["llm_latencia_media_ms"] = round(resumen[0]["lat"], 1) if resumen and resumen[0]["lat"] else 0.0
        return stats
    except PyMongoError as exc:
        raise _envolver("No se pudieron calcular los indicadores", exc) from exc

