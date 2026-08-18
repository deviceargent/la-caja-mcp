"""Mini-falsacion del protocolo de debate: maquina de estados
determinista, solicitud de interferencia y replay de eventos."""

import pytest

from la_caja_mcp.protocolo import ErrorDeProtocolo, Sesion


def sesion_estandar():
    return Sesion(
        claim="la memoria recupera asociaciones dormidas",
        participantes=["claude", "asesor", "humano"],
        arbitro="humano",
    )


def test_proponer_candidate():
    s = sesion_estandar()
    s.mover("proponer", "claude")
    assert s.estado == "candidate"
    assert s.autor == "claude"
    assert s.log[0]["tipo"] == "proponer"


def test_solicitud_de_interferencia_preemptea_a_disputed():
    s = sesion_estandar()
    s.mover("proponer", "claude")
    s.mover("interferir", "asesor", objecion="limite de 1 mes")
    assert s.estado == "disputed"
    assert s.ronda == 1
    assert s.ultimo_interferir_por == "asesor"
    assert s.vence_en_turnos == s.limite_turnos


def test_autor_no_puede_interferir_su_propio_claim():
    s = sesion_estandar()
    s.mover("proponer", "claude")
    with pytest.raises(ErrorDeProtocolo):
        s.mover("interferir", "claude")


def test_no_participante_no_puede_mover():
    s = sesion_estandar()
    with pytest.raises(ErrorDeProtocolo):
        s.mover("proponer", "intruso")


def test_solo_el_autor_responde_a_la_interferencia():
    s = sesion_estandar()
    s.mover("proponer", "claude")
    s.mover("interferir", "asesor")
    with pytest.raises(ErrorDeProtocolo):
        s.mover("responder", "asesor", defensa="x")
    s.mover("responder", "claude", defensa="el umbral es empiral")
    assert s.estado == "disputed"


def test_responder_renueva_la_ronda():
    s = sesion_estandar()
    s.mover("proponer", "claude")
    s.mover("interferir", "asesor")
    s.mover("responder", "claude", defensa="1")
    s.mover("responder", "claude", defensa="2")
    assert s.estado == "disputed"
    assert s.vence_en_turnos == s.limite_turnos


def test_condiciones_lleva_a_conditional():
    s = sesion_estandar()
    s.mover("proponer", "claude")
    s.mover("interferir", "asesor")
    s.mover("responder", "claude", defensa="d")
    s.mover("condiciones", "asesor", lista=["replicar en enron", "frac_rel <= 0.10"])
    assert s.estado == "conditional"
    assert s.condiciones == ["replicar en enron", "frac_rel <= 0.10"]


def test_aceptar_del_interferidor_lleva_a_consensus():
    s = sesion_estandar()
    s.mover("proponer", "claude")
    s.mover("interferir", "asesor")
    s.mover("responder", "claude", defensa="d")
    s.mover("condiciones", "asesor", lista=["replicar en enron"])
    s.mover("aceptar", "asesor")
    assert s.estado == "consensus"


def test_aceptar_solo_del_interferidor_o_arbitro():
    s = Sesion(
        claim="c",
        participantes=["claude", "asesor", "observador", "humano"],
        arbitro="humano",
    )
    s.mover("proponer", "claude")
    s.mover("interferir", "asesor")
    with pytest.raises(ErrorDeProtocolo):
        s.mover("aceptar", "observador")
    s.mover("aceptar", "asesor")
    assert s.estado == "consensus"


def test_aceptar_del_arbitro_es_valido():
    s = sesion_estandar()
    s.mover("proponer", "claude")
    s.mover("interferir", "asesor")
    s.mover("aceptar", "humano")
    assert s.estado == "consensus"


def test_retirar_del_autor_lleva_a_rejected():
    s = sesion_estandar()
    s.mover("proponer", "claude")
    s.mover("interferir", "asesor")
    s.mover("responder", "claude", defensa="d")
    s.mover("retirar", "claude")
    assert s.estado == "rejected"


def test_adjudicacion_solo_humano():
    s = sesion_estandar()
    s.mover("proponer", "claude")
    s.mover("interferir", "asesor")
    with pytest.raises(ErrorDeProtocolo):
        s.mover("adjudicar", "claude", decision="consensus")
    s.mover("adjudicar", "humano", decision="consensus")
    assert s.estado == "consensus"


def test_deadline_vence_y_escala_a_unresolved():
    s = Sesion(claim="c", participantes=["a", "b", "humano"], arbitro="humano", limite_turnos=1)
    s.mover("proponer", "a")
    s.mover("interferir", "b")
    assert s.vence_en_turnos == 1
    with pytest.raises(ErrorDeProtocolo):
        s.mover("escalar", "b")
    s.mover("manifestar", "a", texto="sin novedades")  # turno del autor
    assert s.vence_en_turnos == 0
    s.mover("escalar", "b")
    assert s.estado == "unresolved"


def test_responder_renueva_el_deadline():
    s = Sesion(claim="c", participantes=["a", "b", "humano"], arbitro="humano", limite_turnos=1)
    s.mover("proponer", "a")
    s.mover("interferir", "b")
    s.mover("responder", "a", defensa="d")  # renueva la ronda
    assert s.vence_en_turnos == 1
    with pytest.raises(ErrorDeProtocolo):
        s.mover("escalar", "b")


def test_charla_de_terceros_no_consume_el_deadline():
    s = Sesion(claim="c", participantes=["a", "b", "c", "humano"], arbitro="humano", limite_turnos=1)
    s.mover("proponer", "a")
    s.mover("interferir", "b")
    s.mover("manifestar", "c", texto="opinion")  # no consume turnos del autor
    assert s.vence_en_turnos == 1
    with pytest.raises(ErrorDeProtocolo):
        s.mover("escalar", "b")


def test_estados_terminales_son_estables():
    s = sesion_estandar()
    s.mover("proponer", "claude")
    s.mover("interferir", "asesor")
    s.mover("aceptar", "asesor")
    with pytest.raises(ErrorDeProtocolo):
        s.mover("interferir", "asesor")
    with pytest.raises(ErrorDeProtocolo):
        s.mover("responder", "claude", defensa="d")


def test_supersede_desde_cualquier_estado():
    s = sesion_estandar()
    s.mover("proponer", "claude")
    s.mover("supersede", "asesor", reemplazo="c2")
    assert s.estado == "superseded"


def test_transicion_invalida_no_muta_estado():
    s = sesion_estandar()
    s.mover("proponer", "claude")
    n_log = len(s.log)
    with pytest.raises(ErrorDeProtocolo):
        s.mover("aceptar", "asesor")
    assert s.estado == "candidate"
    assert len(s.log) == n_log


def test_replay_reconstruye_estado_identico():
    s = sesion_estandar()
    s.mover("proponer", "claude")
    s.mover("interferir", "asesor", objecion="limite")
    s.mover("responder", "claude", defensa="d")
    s.mover("condiciones", "asesor", lista=["replicar en enron"])
    s.mover("aceptar", "asesor")
    antes = s.estado_actual()
    r = Sesion.reproducir(s.log)
    assert r.estado_actual() == antes
    assert len(r.log) == len(s.log)


def test_replay_necesita_proponer_inicial():
    with pytest.raises(ErrorDeProtocolo):
        Sesion.reproducir([{"seq": 1, "tipo": "responder"}])


def test_sin_arbitro_no_hay_adjudicacion():
    s = Sesion(claim="c", participantes=["a", "b"])
    s.mover("proponer", "a")
    with pytest.raises(ErrorDeProtocolo):
        s.mover("adjudicar", "b", decision="consensus")


def test_claim_vacio_invalido():
    with pytest.raises(ErrorDeProtocolo):
        Sesion(claim="   ")
