# -*- coding: utf-8 -*-
"""
Hash de senha e migração de contas legadas.

O sistema aceita dois formatos: bcrypt (atual) e SHA-256 (contas antigas, que
migram no primeiro login bem-sucedido). Os testes cobrem os dois caminhos e o
limite de 72 bytes do bcrypt, que já derrubou o cadastro com um 500.
"""

import hashlib

import pytest

pytestmark = pytest.mark.unit


class TestHashBcrypt:
    def test_gera_hash_no_formato_bcrypt(self, app_module):
        assert app_module._hash("senha123").startswith("$2")

    def test_hash_nunca_e_a_senha(self, app_module):
        assert app_module._hash("senha123") != "senha123"

    def test_dois_hashes_da_mesma_senha_diferem(self, app_module):
        """Salt aleatório: hashes iguais denunciariam senhas iguais entre contas."""
        assert app_module._hash("mesma") != app_module._hash("mesma")

    def test_senha_correta_verifica(self, app_module):
        assert app_module._verificar_senha("senha123", app_module._hash("senha123")) is True

    def test_senha_errada_nao_verifica(self, app_module):
        assert app_module._verificar_senha("errada", app_module._hash("senha123")) is False

    def test_acento_na_senha_funciona(self, app_module):
        senha = "coração2026"
        assert app_module._verificar_senha(senha, app_module._hash(senha)) is True


class TestHashLegadoSha256:
    def test_aceita_hash_sha256_antigo(self, app_module):
        legado = hashlib.sha256("antiga".encode()).hexdigest()
        assert app_module._verificar_senha("antiga", legado) is True

    def test_rejeita_senha_errada_no_legado(self, app_module):
        legado = hashlib.sha256("antiga".encode()).hexdigest()
        assert app_module._verificar_senha("outra", legado) is False

    def test_identifica_hash_legado(self, app_module):
        legado = hashlib.sha256(b"x").hexdigest()
        assert app_module._eh_hash_legado(legado) is True

    def test_bcrypt_nao_e_legado(self, app_module):
        assert app_module._eh_hash_legado(app_module._hash("x")) is False


class TestEntradasInvalidas:
    @pytest.mark.parametrize("hash_ruim", ["", None])
    def test_hash_vazio_nunca_autentica(self, app_module, hash_ruim):
        assert app_module._verificar_senha("qualquer", hash_ruim) is False

    def test_hash_corrompido_nao_estoura(self, app_module):
        """bcrypt levanta ValueError em hash malformado; tem que virar False."""
        assert app_module._verificar_senha("x", "$2b$corrompido") is False

    def test_senha_vazia_contra_hash_valido(self, app_module):
        assert app_module._verificar_senha("", app_module._hash("real")) is False

    def test_hash_legado_de_string_arbitraria(self, app_module):
        assert app_module._eh_hash_legado("nao-e-hash-nenhum") is True


class TestLimiteDeSenhaNoCadastro:
    """
    O bcrypt recusa acima de 72 BYTES. Sem validação, a exceção da biblioteca
    subia como 500 e vazava a mensagem interna para o cliente.
    """

    def test_senha_longa_recebe_400(self, client):
        r = client.post("/api/register", json={"username": "u", "password": "a" * 100})
        assert r.status_code == 400

    def test_mensagem_explica_o_limite(self, client):
        r = client.post("/api/register", json={"username": "u", "password": "a" * 100})
        assert "72" in r.get_json()["mensagem"]

    def test_limite_e_em_bytes_nao_caracteres(self, client):
        """
        40 caracteres acentuados ocupam 80 bytes em UTF-8. Se a validação
        contasse caracteres, esta senha passaria e o 500 do bcrypt voltaria.
        """
        senha = "çã" * 20
        assert len(senha) < 72 < len(senha.encode("utf-8")), "premissa do teste"
        r = client.post("/api/register", json={"username": "u", "password": senha})
        assert r.status_code == 400

    def test_campos_vazios_recebem_400(self, client):
        assert (
            client.post("/api/register", json={"username": "", "password": ""}).status_code == 400
        )

    def test_senha_no_limite_passa_da_validacao(self, client, db_falso):
        """
        72 bytes exatos não podem ser barrados pela regra de tamanho. O banco
        está mockado: o que se verifica aqui é só que a validação deixou passar.
        """
        _, conexao = db_falso
        r = client.post("/api/register", json={"username": "u", "password": "a" * 72})
        assert r.status_code != 400 or "72" not in r.get_json().get("mensagem", "")
