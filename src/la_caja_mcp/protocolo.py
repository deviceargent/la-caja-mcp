"""Protocolo de debate agente-agente-humano (prototipo).

Un sistema de claims donde varios agentes (y un humano arbitro) debaten
la validez de una afirmacion. La SOLICITUD DE INTERFERENCIA preemptea el
estado del claim y obliga a responder dentro de una ronda con deadline.

Disciplina de La Caja: toda mutacion pasa por la maquina de estados y
queda en un log de eventos replayable (determinista). Reproducir el log
reconstruye exactamente el estado final.

Estados: candidate, disputed, conditional, consensus, rejected,
superseded, unresolved.
Movimientos: proponer, interferir, responder, condiciones, aceptar,
retirar, adjudicar, escalar, supersede.

Solicitud de interferencia:
- interferir abre una ronda (ronda += 1) con un deadline en turnos.
- El titular del claim (autor) debe responder dentro del deadline; cada
  responder renueva la ronda.
- Si el deadline vence sin respuesta, escalar lleva el claim a unresolved
  (deadlock) y la palabra pasa al humano.
- El humano (arbitro) puede adjudicar en cualquier momento.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ErrorDeProtocolo(ValueError):
    """Movimiento invalido para el estado actual o por autorizacion."""


ESTADOS = (
    "candidate",
    "disputed",
    "conditional",
    "consensus",
    "rejected",
    "superseded",
    "unresolved",
)

MOVIMIENTOS = (
    "proponer",
    "interferir",
    "responder",
    "condiciones",
    "aceptar",
    "retirar",
    "adjudicar",
    "escalar",
    "supersede",
    "manifestar",
)

ESTADOS_TERMINALES = ("consensus", "rejected", "superseded", "unresolved")


@dataclass
class Sesion:
    """Sesion de debate sobre un claim. Inmutable por fuera: solo se
    muta a traves de mover()."""

    claim: str
    contexto: str = ""
    participantes: list[str] = field(default_factory=list)
    arbitro: str | None = None
    limite_turnos: int = 3

    estado: str = "candidate"
    autor: str | None = None
    condiciones: list[str] = field(default_factory=list)
    ronda: int = 0
    ultimo_interferir_por: str | None = None
    vence_en_turnos: int = 0
    log: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.claim, str) or not self.claim.strip():
            raise ErrorDeProtocolo("claim invalido")
        if self.arbitro and self.arbitro not in self.participantes:
            raise ErrorDeProtocolo(f"arbitro {self.arbitro!r} no es participante")

    def _tiene_participacion(self, actor: str) -> bool:
        return actor in self.participantes

    def _registrar(self, tipo: str, actor: str, **payload: Any) -> dict[str, Any]:
        evento = {
            "seq": len(self.log) + 1,
            "tipo": tipo,
            "actor": actor,
            "estado": self.estado,
            **payload,
        }
        self.log.append(evento)
        return evento

    def mover(self, tipo: str, actor: str, **payload: Any) -> dict[str, Any]:
        """Aplica un movimiento validado. Lanza ErrorDeProtocolo si la
        transicion o la autorizacion no son validas. Devuelve el evento."""
        if tipo not in MOVIMIENTOS:
            raise ErrorDeProtocolo(f"movimiento desconocido: {tipo!r}")
        if not self._tiene_participacion(actor):
            raise ErrorDeProtocolo(f"actor {actor!r} no participa en la sesion")

        prev = self.estado
        if tipo == "proponer":
            self._proponer(actor)
        elif tipo == "interferir":
            self._interferir(actor, payload)
        elif tipo == "responder":
            self._responder(actor, payload)
        elif tipo == "condiciones":
            self._condiciones(actor, payload)
        elif tipo == "aceptar":
            self._aceptar(actor)
        elif tipo == "retirar":
            self._retirar(actor)
        elif tipo == "adjudicar":
            self._adjudicar(actor, payload)
        elif tipo == "escalar":
            self._escalar(actor)
        elif tipo == "supersede":
            self._supersede(actor, payload)
        elif tipo == "manifestar":
            self._manifestar(actor, payload)
        else:  # pragma: no cover - cubierto arriba
            raise ErrorDeProtocolo(tipo)

        if (
            prev == "disputed"
            and self.estado == "disputed"
            and actor == self.autor
            and tipo not in ("responder", "escalar")
        ):
            self.vence_en_turnos = max(0, self.vence_en_turnos - 1)
        return self.log[-1]

    def _proponer(self, actor: str) -> None:
        if self.estado != "candidate":
            raise ErrorDeProtocolo("proponer solo desde candidate")
        if self.autor is not None:
            raise ErrorDeProtocolo("el claim ya tiene autor")
        self.autor = actor
        self._registrar(
            "proponer",
            actor,
            claim=self.claim,
            contexto=self.contexto,
            participantes=self.participantes,
            arbitro=self.arbitro,
            limite_turnos=self.limite_turnos,
        )

    def _interferir(self, actor: str, payload: dict[str, Any]) -> None:
        if self.estado not in ("candidate", "conditional"):
            raise ErrorDeProtocolo("interferir solo desde candidate/conditional")
        if actor == self.autor:
            raise ErrorDeProtocolo("el autor no puede interferir su propio claim")
        self.ronda += 1
        self.ultimo_interferir_por = actor
        self.vence_en_turnos = self.limite_turnos
        self.estado = "disputed"
        self._registrar("interferir", actor, objecion=payload.get("objecion", ""))

    def _responder(self, actor: str, payload: dict[str, Any]) -> None:
        if self.estado != "disputed":
            raise ErrorDeProtocolo("responder solo desde disputed")
        if actor != self.autor:
            raise ErrorDeProtocolo("solo el autor responde a la interferencia")
        self.vence_en_turnos = self.limite_turnos
        self._registrar("responder", actor, defensa=payload.get("defensa", ""))

    def _condiciones(self, actor: str, payload: dict[str, Any]) -> None:
        if self.estado not in ("candidate", "disputed", "conditional"):
            raise ErrorDeProtocolo("condiciones no permitidas en este estado")
        lista = payload.get("lista", [])
        if not isinstance(lista, list) or not lista:
            raise ErrorDeProtocolo("condiciones requiere una lista no vacia")
        self.condiciones = [str(c) for c in lista]
        self.estado = "conditional"
        self._registrar("condiciones", actor, lista=self.condiciones)

    def _aceptar(self, actor: str) -> None:
        if self.estado not in ("disputed", "conditional"):
            raise ErrorDeProtocolo("aceptar solo desde disputed/conditional")
        if not (
            actor == self.ultimo_interferir_por
            or (self.arbitro is not None and actor == self.arbitro)
        ):
            raise ErrorDeProtocolo("solo quien interferio o el arbitro aceptan")
        self.estado = "consensus"
        self._registrar("aceptar", actor)

    def _retirar(self, actor: str) -> None:
        if self.estado not in ("candidate", "disputed", "conditional"):
            raise ErrorDeProtocolo("retirar no permitido en este estado")
        if actor != self.autor:
            raise ErrorDeProtocolo("solo el autor retira su claim")
        self.estado = "rejected"
        self._registrar("retirar", actor)

    def _adjudicar(self, actor: str, payload: dict[str, Any]) -> None:
        if self.estado in ESTADOS_TERMINALES:
            raise ErrorDeProtocolo("adjudicar sobre estado terminal")
        if self.arbitro is None:
            raise ErrorDeProtocolo("la sesion no tiene arbitro")
        if actor != self.arbitro:
            raise ErrorDeProtocolo("solo el arbitro humano adjudica")
        decision = payload.get("decision")
        if decision not in ("consensus", "rejected", "unresolved"):
            raise ErrorDeProtocolo(f"decision invalida: {decision!r}")
        self.estado = decision
        self._registrar("adjudicar", actor, decision=decision)

    def _escalar(self, actor: str) -> None:
        if self.estado != "disputed":
            raise ErrorDeProtocolo("escalar solo desde disputed")
        if self.vence_en_turnos > 0:
            raise ErrorDeProtocolo(f"la ronda vence en {self.vence_en_turnos} turnos aun")
        self.estado = "unresolved"
        self._registrar("escalar", actor)

    def _manifestar(self, actor: str, payload: dict[str, Any]) -> None:
        if self.estado in ESTADOS_TERMINALES:
            raise ErrorDeProtocolo("manifestar sobre estado terminal")
        self._registrar("manifestar", actor, texto=payload.get("texto", ""))

    def _supersede(self, actor: str, payload: dict[str, Any]) -> None:
        self.estado = "superseded"
        self._registrar("supersede", actor, reemplazo=payload.get("reemplazo", ""))

    def estado_actual(self) -> dict[str, Any]:
        """Vista serializable del estado, sin el log."""
        return {
            "claim": self.claim,
            "estado": self.estado,
            "autor": self.autor,
            "ronda": self.ronda,
            "ultimo_interferir_por": self.ultimo_interferir_por,
            "vence_en_turnos": self.vence_en_turnos,
            "condiciones": self.condiciones,
            "arbitro": self.arbitro,
        }

    @classmethod
    def reproducir(cls, log: list[dict[str, Any]]) -> "Sesion":
        """Reconstruye una sesion replayando el log de eventos."""
        if not log:
            raise ErrorDeProtocolo("log vacio")
        primero = log[0]
        if primero["tipo"] != "proponer":
            raise ErrorDeProtocolo("el primer evento debe ser proponer")
        sesion = cls(
            claim=primero["claim"],
            contexto=primero.get("contexto", ""),
            participantes=primero.get("participantes", []),
            arbitro=primero.get("arbitro"),
            limite_turnos=primero.get("limite_turnos", 3),
        )
        sesion.autor = primero["actor"]
        sesion.log.append(primero)
        for evento in log[1:]:
            sesion.mover(
                evento["tipo"],
                evento["actor"],
                **{
                    k: v
                    for k, v in evento.items()
                    if k not in ("seq", "tipo", "actor", "estado")
                },
            )
        return sesion
