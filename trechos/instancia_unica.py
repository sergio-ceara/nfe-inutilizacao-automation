"""Garante instância única usando o `bind()` do sistema operacional como
árbitro — CONTEXT.md §11.

Por que não "perguntar antes" (checar `tasklist`/`GET /health` se já existe
outra instância antes de decidir se sobe): isso tem uma janela de corrida
real. Duas instâncias abertas quase ao mesmo tempo podem rodar a checagem
nesse intervalo, as duas concluírem "já tem outra rodando" e as duas
desistirem — **sem nenhuma vencer**, e o app não sobe em lugar nenhum (uma
versão anterior desta checagem, baseada em `tasklist`, reproduziu
exatamente isso com um teste de lançamento simultâneo real).

`bind()` não tem essa brecha: o sistema operacional só deixa **um**
processo reivindicar um `(host, porta)` por vez, de forma atômica — não
existe "os dois acham que ganharam" nem "os dois acham que perderam".
"""
from __future__ import annotations

import socket


def tentar_reservar_porta(host: str, port: int) -> socket.socket | None:
    """Tenta se tornar dono exclusivo de `(host, port)`.

    Devolve o socket (ainda aberto) se conseguir — quem chamar decide o
    que fazer com ele (`run.py` fecha e deixa o Uvicorn bindar de verdade
    logo em seguida). Devolve `None` se a porta já estiver em uso — nesse
    caso, uma outra instância já está rodando.

    Importante: **não** usa `SO_REUSEADDR`. No Windows essa opção afrouxa
    a exclusividade do bind (diferente do comportamento no Linux, onde
    serve principalmente para reaproveitar portas em `TIME_WAIT`) e
    deixaria essa checagem sem efeito nenhum.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        return s
    except OSError:
        s.close()
        return None
