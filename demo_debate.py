"""Demo del protocolo: reproduce el debate de falsacion de La Caja.

Escenario (resumen de lo que paso en el proyecto):
- claude propone el claim de la memoria con olvido.
- asesor interferir (solicitud de interferencia): objeta el presupuesto.
- claude responde, asesor pone condiciones, y se acepta -> consensus.
"""

from la_caja_mcp.protocolo import Sesion

s = Sesion(
    claim="la caja recupera asociaciones observadas con confianza, no inventa memoria",
    participantes=["claude", "asesor", "humano"],
    arbitro="humano",
    limite_turnos=3,
)

movimientos = [
    ("proponer", "claude", {}),
    ("interferir", "asesor", {"objecion": "el presupuesto de primado corta la senal"}),
    ("responder", "claude", {"defensa": "subimos el presupuesto 10 -> 50 y medimos contra el techo"}),
    ("condiciones", "asesor", {"lista": ["presupuesto 50", "C2 = hit@5 >= 0.5 * techo"]}),
    ("aceptar", "asesor", {}),
]

for tipo, actor, payload in movimientos:
    s.mover(tipo, actor, **payload)
    print(f"[{len(s.log):2d}] {tipo:<11} {actor:<8} -> {s.estado}")

print("\nestado final:", s.estado_actual())
print("\nreplay identico:", Sesion.reproducir(s.log).estado_actual() == s.estado_actual())
