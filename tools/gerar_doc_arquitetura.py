# -*- coding: utf-8 -*-
"""
Gera o documento de Arquitetura da Informacao em .docx e .pdf.

    py tools/gerar_doc_arquitetura.py              # data de hoje
    py tools/gerar_doc_arquitetura.py 2026-09-15   # data informada

Sai em docs/SearchPlus_ArquiteturaInformacao_AAAA-MM-DD.{docx,pdf}.

ESCOPO: onde cada coisa mora, como se chama e por quais caminhos se chega
nela. Nao trata de visual, de codigo nem de desempenho.

Os numeros citados foram levantados do proprio repositorio, e nao estimados.
Ao atualizar, refaca a contagem: as consultas estao anotadas em cada linha da
tabela "O mapa de hoje".
"""
import sys

import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from docx_base import (  # noqa: E402
    abrir_miolo, capa, data_do_argumento, novo_documento, nota,
    raiz_do_repositorio, salvar, tabela,
)

L2G = (7.0, 9.0)


def montar(data):
    doc = novo_documento()

    capa(doc,
         "ARQUITETURA DA INFORMAÇÃO",
         ["Onde cada coisa mora,", "como se chama,", "por onde se chega"],
         "Diagnóstico e ajustes no caminho do usuário",
         data,
         ["2 telas · 32 janelas · 8 camadas de sobreposição",
          "branch feature/colecoes-organizacao-e-pastas"])

    abrir_miolo(doc)

    # =====================================================================
    doc.add_heading("O que este documento trata", level=1)
    for t in [
        "Arquitetura da informação é a organização do produto: onde cada função "
        "mora, que nome ela tem, como as partes se relacionam e por quais caminhos "
        "o usuário chega até elas. Não é sobre aparência nem sobre código.",
        "A distinção importa porque quase tudo que está aqui funciona. São "
        "problemas de lugar e de nome, não de defeito. Uma função bem construída "
        "guardada no lugar errado é, para quem usa, uma função que não existe.",
        "Os números vieram do próprio repositório, não de estimativa. As duas "
        "últimas seções são as acionáveis: o que ajustar, e em que ordem.",
    ]:
        doc.add_paragraph(t)

    # =====================================================================
    doc.add_heading("O mapa de hoje", level=1)
    doc.add_paragraph(
        "O que existe hoje, em números. Cada linha diz de onde o número saiu, "
        "para poder ser refeita depois.")
    tabela(doc,
           ("O que", "Quanto", "Como foi contado"),
           [("Telas de verdade", "2",
             "dashboardView e searchResultsView, no index.html"),
            ("Janelas sobrepostas", "32",
             "elementos com “modal” no id"),
            ("Camadas de empilhamento", "8",
             "valores distintos de z-index, de 9.999 a 10.101"),
            ("Endereços de navegação", "0",
             "nenhum uso de histórico ou URL: o app inteiro vive num endereço só"),
            ("Formas de agrupar a mesma foto", "4",
             "categorias, coleções, favoritos e pastas de origem"),
            ("Frases distintas com a palavra “pasta”", "142",
             "textos de tela no index.html e no script.js"),
            ("Controles de aparência", "19",
             "9 seletores de cor, 8 listas e 2 caixas, só na aba Personalização")],
           (5.2, 2.2, 8.6))
    doc.add_paragraph()
    doc.add_paragraph(
        "As duas primeiras linhas explicam a terceira e a quarta. Um aplicativo "
        "com duas telas e trinta e duas janelas não tem para onde navegar: tudo "
        "acontece por cima do mesmo lugar. Por isso não há endereço, não há botão "
        "“voltar” do navegador e não há como mandar a alguém o link de uma coleção.")

    # =====================================================================
    doc.add_heading("Quatro formas de agrupar a mesma foto", level=1)
    doc.add_paragraph(
        "O app oferece quatro maneiras de juntar imagens, e nenhuma tela explica "
        "como elas se relacionam. Quem chega precisa descobrir sozinho, testando.")
    tabela(doc,
           ("Agrupamento", "Quem monta", "Para que serve"),
           [("Categorias", "O app, sozinho",
             "Ver o acervo por assunto sem digitar nada. É o caminho de quem não "
             "usa a busca escrita."),
            ("Coleções", "Você, à mão",
             "Juntar por um critério seu, que a análise automática não teria como "
             "adivinhar. É o único agrupamento que sai para uma pasta."),
            ("Favoritos", "Você, um a um",
             "Marcar para reencontrar depois. Uma lista só, sem nome e sem divisão."),
            ("Pastas", "Sua organização no computador",
             "De onde o arquivo veio. Filtra o que aparece na tela inicial.")],
           (3.4, 4.0, 8.6))
    doc.add_paragraph()
    doc.add_paragraph(
        "Quatro sistemas não é necessariamente demais — cada um responde a uma "
        "pergunta diferente. O problema é que a interface os apresenta lado a "
        "lado, com o mesmo peso, sem dizer qual serve para quê. A consequência "
        "prática aparece no favorito: ele acabou virando um agrupamento de "
        "verdade, com seleção em massa e envio para coleção, mas continua sendo "
        "uma lista única, sem nome — quem favorita por dois motivos diferentes "
        "não tem como separar depois.")

    # =====================================================================
    doc.add_heading("Os problemas, em ordem de impacto", level=1)

    doc.add_heading("1. A palavra “pasta” nomeia cinco coisas diferentes", level=2)
    doc.add_paragraph(
        "É o problema mais sério, porque contamina todas as telas de coleção e "
        "exportação de uma vez. São 142 frases distintas com a palavra, e ela "
        "muda de significado sem aviso:")
    tabela(doc,
           ("Nos textos de hoje", "O que realmente é", "Onde aparece"),
           [("Pasta monitorada, pastas importadas, Gerenciar Pastas",
             "A pasta SUA, no computador, que o app lê para indexar",
             "Menu, tela de pastas, avisos de erro"),
            ("Pasta exportada, pastas geradas",
             "A pasta que o APP CRIA para receber cópias de uma coleção",
             "Tela da coleção, histórico"),
            ("Pasta vinculada",
             "A mesma coisa da linha de cima, com outro nome",
             "Avisos, configurações da coleção"),
            ("Pasta de destino, pasta-mãe",
             "Onde a pasta da coleção vai ser criada",
             "Fluxo de exportação"),
            ("Subpasta por mês",
             "Divisão interna da exportação",
             "Opções de exportação")],
           (4.6, 6.0, 5.4))
    doc.add_paragraph()
    doc.add_paragraph(
        "O caso concreto: o aviso “A pasta vinculada não está mais no lugar” é "
        "sobre uma pasta que o app criou, mas se lê como se um arquivo seu tivesse "
        "sumido. E “fora das pastas monitoradas”, numa mensagem de erro de "
        "exportação, mistura os dois sentidos na mesma frase.")
    nota(doc, "O vocabulário proposto está na seção “Vocabulário”, mais adiante.")

    doc.add_heading("2. Conteúdo do usuário guardado dentro de Configurações", level=2)
    doc.add_paragraph(
        "Três coisas que são CONTEÚDO — e não preferências — moram dentro de "
        "Configurações Gerais, na aba “Desempenho”, logo abaixo de “Modo de Uso "
        "de Hardware (CPU/GPU)”:")
    tabela(doc,
           ("O que está lá", "O que é", "Cliques até chegar"),
           [("Lixeira",
             "O que você excluiu, guardado por 30 dias. É conteúdo seu.", "4"),
            ("Exportações",
             "Histórico do que você mandou para fora. É registro de atividade.", "4"),
            ("Última indexação",
             "O que entrou e o que ficou de fora. É resultado de operação.", "4")],
           (3.6, 9.2, 3.2))
    doc.add_paragraph()
    doc.add_paragraph(
        "Ninguém procura a lixeira dentro de uma aba de desempenho de hardware. "
        "A regra que está sendo quebrada é simples: configurações guardam "
        "escolhas; conteúdo mora onde se navega. Estes três são lugares, não "
        "ajustes.")

    doc.add_heading("3. O menu diz “Navegação”, mas não navega", level=2)
    doc.add_paragraph(
        "O menu lateral tem uma seção chamada Navegação, com Início, Coleções e "
        "Favoritos. Dos três, só Início leva a algum lugar — os outros dois abrem "
        "uma janela por cima de onde você estava. O rótulo promete uma coisa e a "
        "interação entrega outra.")
    doc.add_paragraph(
        "Isso tem consequências que aparecem no uso diário: não dá para voltar "
        "com o botão do navegador, não dá para abrir uma coleção e a busca ao "
        "mesmo tempo, não dá para mandar a alguém o endereço de uma coleção, e "
        "fechar a janela sempre devolve ao mesmo ponto de partida, mesmo quando "
        "você veio de outro lugar.")

    doc.add_heading("4. Duas entradas quase homônimas para aparência", level=2)
    tabela(doc,
           ("O que o menu do perfil oferece", "Para onde vai"),
           [("Personalização Visual", "Um painel lateral de configuração"),
            ("Configurações Gerais",
             "Uma janela que tem, dentro dela, uma aba chamada “Personalização”")],
           L2G)
    doc.add_paragraph()
    doc.add_paragraph(
        "Dois itens de menu com quase o mesmo nome, levando a lugares diferentes, "
        "os dois sobre aparência. Não há como acertar na primeira tentativa a não "
        "ser por sorte.")

    doc.add_heading("5. Janelas sobre janelas, até oito camadas", level=2)
    doc.add_paragraph(
        "Exportar uma coleção que já tem pasta pode empilhar: lista de coleções → "
        "conteúdo da coleção → aviso de que já existe pasta → escolha do nome → "
        "opções de exportação → confirmação. Cinco camadas, sem nenhuma trilha na "
        "tela dizendo onde você está nem como voltar um passo.")
    doc.add_paragraph(
        "O Esc já fecha a janela de cima, uma de cada vez — isso foi corrigido. O "
        "que falta não é a tecla: é a profundidade em si.")

    doc.add_heading("6. A tela inicial não recebe quem chega", level=2)
    doc.add_paragraph(
        "Um usuário que acabou de instalar, sem nenhuma pasta importada, vê a tela "
        "inicial COMPLETAMENTE EM BRANCO: nenhuma mensagem, nenhum próximo passo. "
        "A busca tem um estado vazio bem resolvido, que explica a situação e "
        "oferece o botão certo. A tela inicial não tem — e é ela que aparece "
        "primeiro.")
    nota(doc, "Defeito, não decisão de projeto: script.js, em carregarGaleria. "
              "A mensagem existe, mas está condicionada a um estado que o usuário "
              "novo nunca tem. Correção de uma linha.")

    # =====================================================================
    doc.add_heading("O caminho do usuário: onde ele trava", level=1)
    doc.add_paragraph(
        "Cinco percursos reais, contados em cliques, do começo até o objetivo.")

    tabela(doc,
           ("Percurso", "Como é hoje", "Onde trava"),
           [("Primeiro uso: entrar e entender o que fazer",
             "Login → tela em branco.",
             "Trava no primeiro segundo. Nada na tela diz que é preciso importar "
             "uma pasta. (Problema 6)"),

            ("Recuperar uma coleção excluída por engano",
             "Avatar → Configurações Gerais → aba Desempenho → Lixeira. 4 cliques.",
             "Trava antes do primeiro clique: não há motivo para procurar em "
             "“Desempenho”. Quem não viu o aviso de 8 segundos conclui que perdeu. "
             "(Problema 2)"),

            ("Descobrir para onde as fotos da coleção estão indo",
             "Coleções → abrir a coleção → Configurações → ler o destino.",
             "O texto usa “pasta vinculada”, “pasta exportada” e “pasta de "
             "destino” para a mesma coisa. (Problema 1)"),

            ("Voltar da coleção para os resultados da busca",
             "Fechar a janela da coleção.",
             "Só existe um caminho de volta, e ele sempre leva ao mesmo lugar, "
             "independentemente de onde você veio. (Problema 3)"),

            ("Mudar a cor do app",
             "Avatar → escolher entre dois itens de nome parecido.",
             "Metade das vezes abre o painel errado. (Problema 4)")],
           (4.0, 5.6, 6.4))

    # =====================================================================
    doc.add_heading("Vocabulário: o que passar a chamar de quê", level=1)
    doc.add_paragraph(
        "A correção do problema 1 é uma decisão de vocabulário, não de código: "
        "escolher um nome por conceito e usar sempre o mesmo. A proposta parte de "
        "distinguir o que é seu do que o app criou, porque é essa a confusão que "
        "gera medo de perder arquivo.")
    tabela(doc,
           ("Conceito", "Passa a se chamar", "Por quê"),
           [("A pasta do seu computador que o app lê",
             "**Pasta do computador",
             "Deixa claro que é sua e que o app só lê. Substitui “monitorada”, "
             "“importada” e “indexada”."),
            ("A pasta que o app cria para uma coleção",
             "**Pasta da coleção",
             "O nome diz de quem ela é. Substitui “exportada”, “gerada” e "
             "“vinculada”, que hoje são três nomes para isto."),
            ("Onde a pasta da coleção é criada",
             "**Onde salvar",
             "É uma escolha do momento, não um conceito que precise de nome "
             "próprio. Substitui “pasta-mãe” e “pasta de destino”."),
            ("Copiar a coleção para o computador",
             "**Salvar no computador",
             "“Exportar” é palavra de sistema, não de quem guarda foto. Ficaria "
             "só onde já virou nome de tela."),
            ("A ação de ler uma pasta pela primeira vez",
             "**Adicionar pasta",
             "Um verbo só. Hoje convivem “Adicionar”, “Importar”, “Gerenciar” e "
             "“Analisar” para passos do mesmo fluxo.")],
           (4.8, 3.8, 7.4))
    doc.add_paragraph()
    doc.add_paragraph(
        "A troca é mecânica e de baixo risco: mexe em texto de tela, não em "
        "comportamento. O maior cuidado é não deixar meio caminho — dois "
        "vocabulários convivendo é pior que o de hoje.")

    # =====================================================================
    doc.add_heading("O que ajustar, em ordem", level=1)
    doc.add_paragraph(
        "Ordenado por quanto melhora dividido por quanto custa. Os três primeiros "
        "resolvem a maior parte do incômodo e não mexem em como o app funciona.")
    tabela(doc,
           ("#", "Ajuste", "Esforço", "O que resolve"),
           [("1", "Fazer a tela inicial receber quem chega: mensagem e botão "
                  "“Adicionar pasta” quando não há nada indexado.",
             "Muito baixo", "Problema 6. É o primeiro segundo do produto."),
            ("2", "Tirar Lixeira, Exportações e Última indexação de dentro de "
                  "Configurações e pô-las no menu lateral.",
             "Baixo", "Problema 2. Três funções que hoje ninguém acha."),
            ("3", "Unificar o vocabulário de “pasta”, conforme a tabela anterior.",
             "Médio", "Problema 1. Some o medo de o app apagar arquivo seu."),
            ("4", "Juntar “Personalização Visual” e a aba “Personalização” num "
                  "lugar só.",
             "Baixo", "Problema 4."),
            ("5", "Encurtar o empilhamento da exportação, juntando o aviso de "
                  "pasta existente com a escolha do nome.",
             "Médio", "Problema 5. De cinco camadas para três."),
            ("6", "Dar nome aos favoritos, ou assumir que favorito é marcação e "
                  "coleção é agrupamento.",
             "Médio", "A ambiguidade entre os quatro agrupamentos."),
            ("7", "Transformar Coleções e Favoritos em telas de verdade, com "
                  "endereço próprio.",
             "Alto", "Problema 3. Traz botão “voltar” e link compartilhável.")],
           (0.9, 7.2, 2.2, 5.7), negrito_primeira=False)
    doc.add_paragraph()
    doc.add_paragraph(
        "O item 7 é o único que mexe na estrutura do app, e por isso está por "
        "último apesar de resolver o problema mais profundo. Os seis primeiros "
        "cabem em texto, posição de menu e organização de janelas.")

    # =====================================================================
    doc.add_heading("O que já está bem resolvido", level=1)
    doc.add_paragraph(
        "Registrado para não ser desfeito sem querer numa reorganização.")
    tabela(doc,
           ("O que", "Por que funciona"),
           [("O estado vazio da busca",
             "Quando não acha nada, diz o motivo provável e oferece caminhos que "
             "levam a resultado. É o modelo a seguir na tela inicial."),
            ("O seletor de pastas da tela inicial",
             "Fica onde o conteúdo que ele filtra está, mostra nome e quantidade, "
             "e fecha ao escolher."),
            ("A explicação de por que um resultado apareceu",
             "Responde a pergunta no lugar onde ela nasce, sem jargão."),
            ("O desfazer em duas camadas",
             "Aviso imediato para o engano recente, lixeira para o resto. A "
             "estrutura está certa; só o lugar da lixeira é que está errado."),
            ("A aba de configurações da coleção",
             "Reúne o que é daquela coleção dentro dela, em vez de mandar para as "
             "configurações gerais. É o padrão que o item 2 propõe generalizar.")],
           (5.4, 10.6))

    return salvar(doc, "SearchPlus_ArquiteturaInformacao", data)


if __name__ == "__main__":
    raiz_do_repositorio()
    for caminho in montar(data_do_argumento(sys.argv)):
        if caminho:
            print(os.path.relpath(caminho).replace("\\", "/"))
