# -*- coding: utf-8 -*-
"""
`/api/open_location` — a rota que abre o Explorer num arquivo.

Era a única porta sem tranca do projeto. Bastava o caminho existir:
`?path=C:\\Users\\x\\.ssh\\id_rsa` abria o Explorer ali, apesar de
`/api/file` — que serve o mesmo tipo de recurso — já recusar exatamente isso.

A bateria é quase toda negativa. O caminho feliz depende do Windows e de um
`subprocess`; o que importa aqui é o que a rota **recusa**.

Nota sobre `realpath` vs `normpath`: a validação resolve links antes de
comparar. Um symlink dentro da pasta monitorada apontando para fora passaria
pela comparação textual, porque o caminho *escrito* continua dentro dela.
"""

import os

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def monitorada(tmp_path):
    """Pasta monitorada com um arquivo dentro."""
    p = tmp_path / "Fotos"
    p.mkdir()
    (p / "foto.jpg").write_text("x", encoding="utf-8")
    return p


def _rotas(pastas):
    return {"SELECT path FROM folders": {"fetchall": [{"path": str(p)} for p in pastas]}}


class TestRecusa:
    def test_travessia_com_pontos(self, client_logado, db_roteado, monitorada, tmp_path):
        """O clássico: `../../` saindo da raiz indexada."""
        segredo = tmp_path / "segredo.txt"
        segredo.write_text("chave", encoding="utf-8")

        db_roteado(_rotas([monitorada]))
        alvo = str(monitorada / ".." / "segredo.txt")
        r = client_logado.get(f"/api/open_location?path={alvo}")

        assert r.status_code == 403

    def test_caminho_absoluto_fora_das_raizes(
        self, client_logado, db_roteado, monitorada, tmp_path
    ):
        fora = tmp_path / "outra" / "arquivo.txt"
        fora.parent.mkdir()
        fora.write_text("x", encoding="utf-8")

        db_roteado(_rotas([monitorada]))
        r = client_logado.get(f"/api/open_location?path={fora}")

        assert r.status_code == 403

    @pytest.mark.skipif(os.name != "nt", reason="symlink exige privilégio no Windows")
    def test_symlink_apontando_para_fora(self, client_logado, db_roteado, monitorada, tmp_path):
        """
        O caminho *escrito* fica dentro da pasta monitorada; o destino, não.
        Só `realpath` pega este — `normpath` deixaria passar.
        """
        fora = tmp_path / "fora.txt"
        fora.write_text("segredo", encoding="utf-8")
        link = monitorada / "atalho.txt"
        try:
            link.symlink_to(fora)
        except (OSError, NotImplementedError):
            pytest.skip("sem permissão para criar symlink neste ambiente")

        db_roteado(_rotas([monitorada]))
        r = client_logado.get(f"/api/open_location?path={link}")

        assert r.status_code == 403

    @pytest.mark.skipif(os.name != "nt", reason="junction é específica do Windows")
    def test_junction_apontando_para_fora(self, client_logado, db_roteado, monitorada, tmp_path):
        """
        Mesma classe do symlink, mas *sem* exigir privilégio — junction de
        diretório qualquer usuário cria. É a prova que o teste de symlink não
        consegue dar neste ambiente.

        Verificado à mão: com `normpath` este caminho era autorizado (True);
        com `realpath`, recusado (False).
        """
        import subprocess as sp

        fora = tmp_path / "Secreto"
        fora.mkdir()
        (fora / "chave.txt").write_text("segredo", encoding="utf-8")
        atalho = monitorada / "atalho"

        # `/d` ignora o AutoRun do cmd: um script de perfil que falhe suja o
        # código de retorno mesmo quando o mklink funcionou. Confia-se no
        # resultado em disco, não no returncode.
        sp.run(["cmd", "/d", "/c", "mklink", "/J", str(atalho), str(fora)], capture_output=True)
        if not (atalho / "chave.txt").exists():
            pytest.skip("não foi possível criar junction neste ambiente")

        db_roteado(_rotas([monitorada]))
        resp = client_logado.get(f"/api/open_location?path={atalho / 'chave.txt'}")

        assert resp.status_code == 403

    def test_prefixo_parecido_nao_autoriza(self, client_logado, db_roteado, tmp_path):
        """`C:\\Fotos` não pode autorizar `C:\\Fotos_privado`."""
        (tmp_path / "Fotos").mkdir()
        vizinha = tmp_path / "Fotos_privado"
        vizinha.mkdir()
        alvo = vizinha / "a.jpg"
        alvo.write_text("x", encoding="utf-8")

        db_roteado(_rotas([tmp_path / "Fotos"]))
        r = client_logado.get(f"/api/open_location?path={alvo}")

        assert r.status_code == 403

    def test_sem_pastas_monitoradas_nada_e_autorizado(self, client_logado, db_roteado, monitorada):
        db_roteado(_rotas([]))
        r = client_logado.get(f"/api/open_location?path={monitorada / 'foto.jpg'}")
        assert r.status_code == 403

    def test_caminho_vazio(self, client_logado, db_roteado):
        db_roteado(_rotas([]))
        assert client_logado.get("/api/open_location?path=").status_code == 400

    def test_exige_sessao(self, client, db_roteado, monitorada):
        db_roteado({})
        r = client.get(f"/api/open_location?path={monitorada / 'foto.jpg'}")
        assert r.status_code == 401

    def test_rejeicao_nao_e_500(self, client_logado, db_roteado, monitorada, tmp_path):
        """Caminho malformado é recusa, não estouro."""
        db_roteado(_rotas([monitorada]))
        for ruim in ["....//....//etc/passwd", "C:\\\\?\\\\C:\\Windows", "\x00"]:
            r = client_logado.get(f"/api/open_location?path={ruim}")
            assert r.status_code in (400, 403, 404), f"{ruim!r} devolveu {r.status_code}"


class TestAceita:
    def test_arquivo_dentro_da_pasta_passa_pela_autorizacao(
        self, client_logado, db_roteado, monitorada
    ):
        db_roteado(_rotas([monitorada]))
        r = client_logado.get(f"/api/open_location?path={monitorada / 'foto.jpg'}")
        # 200 no Windows; 501 em outro SO. O que importa é NÃO ser 403.
        assert r.status_code != 403

    def test_arquivo_em_subpasta(self, client_logado, db_roteado, monitorada):
        sub = monitorada / "2024"
        sub.mkdir()
        alvo = sub / "b.jpg"
        alvo.write_text("x", encoding="utf-8")

        db_roteado(_rotas([monitorada]))
        assert client_logado.get(f"/api/open_location?path={alvo}").status_code != 403

    def test_autorizado_mas_ausente_da_404(self, client_logado, db_roteado, monitorada):
        db_roteado(_rotas([monitorada]))
        r = client_logado.get(f"/api/open_location?path={monitorada / 'sumiu.jpg'}")
        assert r.status_code == 404
