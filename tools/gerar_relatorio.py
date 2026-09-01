# -*- coding: utf-8 -*-
"""
Gera o relatorio de implementacao em .docx e .pdf.

    py tools/gerar_relatorio.py              # usa a data de hoje
    py tools/gerar_relatorio.py 2026-09-15   # usa a data informada

Sai em docs/SearchPlus_Implementacoes_AAAA-MM-DD.{docx,pdf}. Cada rodada gera
um arquivo novo, com data no nome, em vez de sobrescrever: a ideia e ter o
historico do que foi entregue em cada momento, e nao so a foto de agora.

A forma -- capa, estilos, tabelas e conversao para PDF -- vem de docx_base.py.
Aqui fica so o CONTEUDO.

AO ACRESCENTAR UMA FEATURE: some um capitulo em CAPITULOS, atualize os numeros
do RESUMO e, se for o caso, DECISOES. O texto de cada linha deve caber na frase
"antes o usuario fazia X, agora faz Y" -- se nao couber, provavelmente e
detalhe tecnico, e o lugar dele e o markdown dos requisitos.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from docx_base import (  # noqa: E402
    abrir_miolo, capa, data_do_argumento, novo_documento, nota,
    raiz_do_repositorio, salvar, tabela,
)

RESUMO = [
    ("Requisitos funcionais especificados", "338"),
    ("Requisitos implementados ou corrigidos", "337"),
    ("Requisitos fora de escopo, por decisão registrada", "1"),
    ("Testes automatizados passando", "799"),
    ("Áreas do produto afetadas", "12"),
]

CAPITULOS = [
    ("1. Encontrar as coisas: a busca",
     "A busca é o coração do produto. As mudanças aqui foram menos sobre achar "
     "melhor e mais sobre não obrigar o usuário a recomeçar do zero quando o "
     "resultado não é o esperado.",
     [
         ("Limpar o campo",
          "Apagava letra por letra, ou selecionava tudo e deletava.",
          "Um × dentro do campo limpa de uma vez e deixa o cursor pronto para digitar. "
          "Os resultados na tela continuam lá: limpar o texto e sair da tela de "
          "resultados são coisas diferentes."),
         ("Tirar um assunto do resultado",
          "Se a busca trazia coisa demais, era preciso reescrever a frase inteira.",
          "Escrever “-palavra” tira aquele assunto. Vale para o texto e também para a "
          "imagem, porque a maioria das fotos com gente não tem a palavra “pessoas” "
          "escrita em lugar nenhum."),
         ("Pesquisar dentro do que já apareceu",
          "Cada nova busca varria a biblioteca inteira outra vez.",
          "“Buscar dentro destes” limita a próxima busca ao que está na tela — útil "
          "para ir afunilando sem perder o caminho."),
         ("Ver e desfazer os filtros",
          "Não dava para saber o que estava filtrando o resultado.",
          "Uma trilha mostra cada refinamento aplicado, e cada um sai sozinho com um "
          "clique. Aparece também quando a busca não achou nada, que é justamente "
          "quando o caminho de volta é remover um filtro."),
         ("Buscar só entre os favoritos",
          "O favorito só servia para reencontrar depois, na aba de favoritos.",
          "Um botão “Favoritos” na barra restringe a busca ao que você marcou, e "
          "combina com os outros filtros em vez de substituí-los."),
         ("Saber por que um resultado apareceu",
          "O resultado aparecia sem explicação.",
          "Cada um traz uma etiqueta com o motivo: a aparência, o que a imagem mostra, "
          "o texto do documento ou o nome do arquivo."),
         ("Quando não acha nada",
          "A tela dizia apenas “nada encontrado”.",
          "Explica o motivo provável e sugere categorias que têm conteúdo, além das "
          "buscas recentes — caminhos que levam a resultado de verdade."),
     ],
     "RF-001 a RF-012 · RF-193 a RF-199 · RF-219 a RF-233 · RF-265 a RF-267"),

    ("2. A tela inicial",
     "Muita gente não usa a busca escrita: navega pelas categorias que a análise "
     "monta sozinha. A tela inicial passou a ser um lugar de trabalho, e não só "
     "uma vitrine.",
     [
         ("Ver a home logo ao entrar",
          "As pastas importadas só apareciam depois da primeira busca.",
          "As categorias aparecem desde o login."),
         ("Escolher quais pastas aparecem",
          "Tudo o que foi importado se misturava nas mesmas categorias, sem dizer de "
          "onde cada imagem veio.",
          "Um botão no canto lista as pastas importadas com nome e quantidade, e você "
          "escolhe quais mostrar. A escolha fica guardada na conta, não no navegador."),
         ("Deixar a home limpa",
          "Desmarcar todas as pastas voltava a mostrar tudo — a escolha era ignorada.",
          "Nenhuma pasta marcada mostra nenhuma pasta, para quem quer só a barra de "
          "busca. Há um atalho “Não mostrar nenhuma” no menu."),
         ("Selecionar sem passar pela busca",
          "Para juntar fotos numa coleção era preciso buscar antes.",
          "Cada card tem caixa de seleção, e cada categoria tem “Selecionar tudo”. A "
          "mesma foto que aparece em duas categorias marca nas duas."),
         ("Favoritar na home",
          "Era preciso abrir a imagem para marcar a estrela.",
          "O card tem botão de favoritar, e marcar atualiza todos os cards daquela "
          "imagem de uma vez."),
     ],
     "RF-234 a RF-249 · RF-259 a RF-264"),

    ("3. Selecionar imagens",
     "Selecionar e favoritar são coisas diferentes: uma é um passo de trabalho, "
     "a outra é uma marcação que dura. O app passou a tratá-las assim.",
     [
         ("Selecionar sem favoritar",
          "Só existia o coração, que serve para outra finalidade.",
          "Caixa de seleção própria, à esquerda do card. Selecionar não favorita e "
          "desfavoritar não tira da seleção."),
         ("Marcar tudo de uma vez",
          "Marcava-se uma a uma.",
          "Um botão marca todos os resultados da busca atual; o mesmo botão desmarca "
          "quando tudo já está marcado. O rótulo diz o que o clique vai fazer."),
         ("Não perder a seleção",
          "Trocar de filtro ou recarregar a página apagava tudo.",
          "A seleção sobrevive à troca de filtro e ao recarregamento. Fechar a aba "
          "limpa: continua sendo passo de trabalho, não algo para guardar."),
         ("Saber quantas estão marcadas",
          "Não havia contagem.",
          "A barra mostra quantos resultados existem e quantos estão marcados."),
         ("Arquivo que sumiu do disco",
          "Entraria na coleção como um item quebrado.",
          "Ao restaurar a seleção, o que não existe mais é descartado e você é avisado "
          "de quantos saíram — para não estranhar o número menor."),
     ],
     "RF-013 a RF-021 · RF-065 a RF-072 · RF-278 a RF-283"),

    ("4. Coleções",
     "A coleção é o agrupamento manual, feito por você, ao lado das categorias "
     "automáticas. Ganhou as operações que faltavam para ser usável no dia a dia.",
     [
         ("Adicionar várias de uma vez",
          "Uma imagem por vez, abrindo cada uma.",
          "Tudo o que está selecionado entra numa ação só, e o app informa quantas "
          "entraram e quantas já estavam lá."),
         ("Renomear",
          "Não era possível.",
          "Renomeia pelo cabeçalho da coleção ou pelas configurações. As pastas já "
          "exportadas acompanham o novo nome."),
         ("Ordenar a lista",
          "Ordem fixa.",
          "Por mais recentes, mais antigas, nome ou quantidade de itens. A escolha "
          "sobrevive ao recarregamento."),
         ("Escolher a capa",
          "A capa era sempre o mosaico automático das últimas imagens.",
          "Dá para escolher a imagem da capa. O mosaico continua sendo o padrão, e a "
          "coleção volta a ele sozinha se a imagem escolhida sair da biblioteca."),
         ("Transformar favoritos em coleção",
          "Os favoritos não conversavam com as coleções.",
          "Na aba de favoritos, selecione um ou todos e mande para uma coleção "
          "existente, ou crie uma na hora. Ao terminar, o app leva você até ela."),
         ("Abrir a lista de coleções",
          "A tela fazia uma consulta ao banco por coleção; com muitas, demorava.",
          "Uma consulta só, independente de quantas coleções existam."),
     ],
     "RF-022 a RF-032 · RF-151 a RF-153 · RF-250 a RF-258 · RF-268 a RF-276"),

    ("5. Exportar para uma pasta do computador",
     "Exportar é copiar as imagens da coleção para uma pasta comum do Windows, "
     "para levar num pendrive, mandar para alguém ou abrir em outro programa. "
     "Os arquivos originais nunca são movidos nem apagados.",
     [
         ("Exportar logo depois de adicionar",
          "Adicionar e exportar eram passos separados; era fácil esquecer o segundo.",
          "Terminada a adição, o app oferece exportar aquela coleção na hora."),
         ("Escolher o que sai",
          "Saía tudo, do jeito que estava.",
          "Só imagens, só documentos ou tudo. Dá para renomear em lote com um padrão, "
          "reduzir o tamanho das imagens e organizar a saída em subpastas por mês."),
         ("Nome dos arquivos",
          "O nome original, e ponto.",
          "Padrão configurável, com numeração que usa zeros à esquerda — sem eles o "
          "Explorer ordena 1, 10, 11, 2. A extensão nunca vem do padrão: trocá-la não "
          "converte o arquivo, só faz abrir com o programa errado."),
         ("Escolher a pasta de destino",
          "Escolhia-se a pasta a cada exportação.",
          "A última pasta usada já vem preenchida."),
         ("Exportar a mesma coleção de novo",
          "Criava outra pasta sem avisar, e não dava para saber qual era qual.",
          "O app avisa que a coleção já tem pasta e quantas. O nome da coleção é sempre "
          "o começo do nome da pasta, e você escolhe o complemento em vez da "
          "numeração automática."),
         ("Saber o que já foi exportado",
          "Exportou e acabou; não ficava registro.",
          "Um histórico mostra o que foi, quando, para onde e o que falhou — e diz se "
          "a pasta ainda existe, para não oferecer um botão que não abre nada."),
         ("Consertar o que falhou",
          "Era preciso refazer a exportação inteira.",
          "“Tentar de novo” repete só os que falharam, na mesma pasta. “Tirar da "
          "coleção os que sumiram” limpa os arquivos que não estão mais no disco — "
          "conferindo na hora, porque o disco externo pode ter sido reconectado."),
     ],
     "RF-033 a RF-064 · RF-073 a RF-079 · RF-284 a RF-306"),

    ("6. Pasta vinculada: a coleção que se mantém sozinha",
     "Este foi o incômodo mais concreto relatado: adicionar uma foto nova a uma "
     "coleção já exportada não colocava a foto na pasta. A coleção e a pasta "
     "passaram a andar juntas.",
     [
         ("Quando o app pergunta o destino",
          "Perguntava a cada foto adicionada — repetitivo e fácil de errar.",
          "Pergunta uma vez, na criação da coleção, com três opções: enviar sempre sem "
          "perguntar, perguntar antes de cada envio, ou não enviar. Uma animação curta "
          "mostra o que cada opção faz."),
         ("Mudar de ideia depois",
          "A escolha ficava presa ao momento da criação.",
          "A aba “Configurações” dentro da coleção muda o modo e o destino a qualquer "
          "momento, e mostra qual está em vigor."),
         ("Foto nova numa coleção já exportada",
          "A foto entrava na coleção mas não aparecia na pasta.",
          "No modo “enviar sempre”, é copiada na hora — e só ela, não a coleção "
          "inteira. Adicionar 1 foto a uma coleção de 300 copia 1 arquivo."),
         ("Mais de uma pasta de destino",
          "Um destino só por coleção.",
          "Dá para marcar várias pastas para receber ao mesmo tempo, espelhando a "
          "coleção em mais de um lugar — ou nenhuma, parando só o envio automático "
          "sem perder as pastas já criadas."),
         ("Remover uma imagem da coleção",
          "A cópia continuava na pasta exportada, e a pasta ia ficando desatualizada.",
          "A cópia sai junto, conforme o modo escolhido. O arquivo original nas suas "
          "pastas nunca é tocado."),
         ("Ver o que já foi para a pasta",
          "Não havia como conferir sem abrir o Explorer e comparar na mão.",
          "“Status da pasta” mostra, por pasta, o que já foi copiado e o que falta, com "
          "nomes — e copia as faltantes ali mesmo. Também lista arquivos que estão na "
          "pasta mas não na coleção."),
         ("Excluir a coleção",
          "A coleção sumia e as pastas ficavam no disco sem explicação.",
          "O app pergunta o que fazer com cada pasta, mostrando caminho completo e "
          "quantidade de arquivos. Manter é uma opção de primeira classe. Apagar exige "
          "duas etapas, e o aviso diz que não vai para a Lixeira do Windows."),
     ],
     "RF-080 a RF-146"),

    ("7. A análise das imagens",
     "Ao importar uma pasta, cada arquivo passa por uma análise que é o que "
     "permite buscar por significado depois. É demorada, e o problema era não "
     "saber o que estava acontecendo.",
     [
         ("Saber quanto falta",
          "A barra dizia “N na fila”, que não responde a pergunta real: dá tempo de "
          "almoçar?",
          "Mostra o tempo restante, calculado pelo ritmo que a análise está de fato "
          "conseguindo na sua máquina. Abaixo de um minuto, diz “quase terminando” em "
          "vez de um número."),
         ("Saber o que entrou e o que ficou de fora",
          "A análise terminava e pronto.",
          "Um resumo por pasta com indexados, ignorados e com erro — separados, porque "
          "um .zip no meio das fotos não é defeito. Os erros abrem com nome e motivo. "
          "Fica guardado e reabre pelas Configurações."),
         ("Pasta que mudou depois de importada",
          "Só reimportando a pasta inteira.",
          "Um botão “Verificar” em cada pasta acha o que é novo, o que foi alterado e "
          "o que sumiu, e responde na hora com os números e os nomes."),
         ("Arquivo que sumiu do disco",
          "Não havia tratamento.",
          "É marcado, nunca apagado: o motivo mais comum é um disco externo "
          "desconectado, e apagar jogaria fora a descrição e a participação em "
          "coleções. Volta sozinho quando reaparece."),
     ],
     "RF-154 a RF-168 · RF-200 a RF-218"),

    ("8. Abrir o programa",
     "O aplicativo carrega modelos de análise pesados ao iniciar. Antes, ele "
     "carregava tudo antes de responder qualquer coisa.",
     [
         ("Esperar para ver a tela",
          "Cerca de 30 segundos sem nada. O navegador dizia “não foi possível acessar "
          "este site” e a conclusão natural era que o programa não tinha aberto.",
          "A tela aparece em cerca de 2 segundos, e a análise continua carregando por "
          "trás. Medido: 29,7s para ~2,2s."),
         ("Buscar antes de tudo carregar",
          "A busca podia devolver uma lista vazia, que se lê como “não tem nada”.",
          "Um aviso discreto diz que a busca está sendo preparada e some sozinho. "
          "Buscar cedo demais recebe “tente de novo em instantes”."),
         ("Mensagens de erro",
          "Citavam nomes internos, como “SBERT indisponível”.",
          "Nenhuma mensagem cita nome de modelo ou termo técnico."),
     ],
     "RF-169 a RF-179"),

    ("9. Desfazer",
     "Excluir era definitivo e imediato. Passou a haver uma rede de proteção em "
     "duas camadas.",
     [
         ("Excluir uma coleção por engano",
          "Excluiu, perdeu.",
          "Um aviso com “desfazer” fica 8 segundos na tela. Quem perder esse tempo "
          "encontra o item na lixeira, dentro das Configurações, por 30 dias."),
         ("Remover imagens de uma coleção",
          "Mesma situação.",
          "Mesmo desfazer."),
         ("O que volta ao restaurar",
          "—",
          "A coleção volta com o mesmo identificador, com as pastas geradas e com o "
          "modo de envio. Imagem que você apagou da biblioteca nesse meio-tempo é "
          "pulada, em vez de fazer a restauração inteira falhar."),
         ("Descartar da lixeira",
          "—",
          "É a única exclusão sem desfazer do app, e pede confirmação. É assim de "
          "propósito: a lixeira é o desfazer."),
     ],
     "RF-180 a RF-192"),

    ("10. Acessibilidade",
     "Um conjunto de correções para que o app funcione para quem usa leitor de "
     "tela, navega por teclado ou não distingue certas cores.",
     [
         ("Escolher uma cor ilegível",
          "Era possível escolher qualquer cor de destaque, inclusive uma que não dava "
          "para ler.",
          "O contraste é medido no momento da escolha, contra o fundo em que a cor vai "
          "ser lida de verdade. Abaixo do mínimo, o app avisa e oferece o tom mais "
          "próximo que passa — quem escolheu aquela cor queria aquela cor."),
         ("O tema que já vinha instalado",
          "Três combinações do tema padrão estavam abaixo do mínimo de leitura.",
          "Auditado e corrigido."),
         ("Mudanças na tela",
          "Passavam em silêncio para quem usa leitor de tela.",
          "Progresso da análise, contagem de resultados e avisos são anunciados. Erro "
          "interrompe a leitura; o resto espera a pausa."),
         ("Teclado nas janelas",
          "Das 23 janelas do app, 14 fechavam com Esc; nove não tinham tecla nenhuma.",
          "Todas fecham com Esc. O foco entra na janela ao abrir, fica preso dentro "
          "dela enquanto está aberta e volta ao botão que a abriu."),
         ("Descrição das imagens",
          "As imagens iam sem texto alternativo.",
          "A descrição gerada pela análise vira o texto alternativo."),
         ("Favorito sem indicação",
          "Favoritava e o botão ficava vazio — um círculo em branco, sem informação.",
          "O coração passa de vazado a preenchido: a diferença não é só de cor, então "
          "funciona para quem não distingue as duas."),
     ],
     "RF-147 a RF-150 · RF-307 a RF-327 · RF-335"),

    ("11. Aparência dos ícones",
     "Os ícones da interface eram emoji. Foram substituídos por um conjunto "
     "desenhado, com 35 símbolos no mesmo traço.",
     [
         ("Ícone e tema",
          "Emoji são coloridos pela fonte do sistema. Ignoravam o tema e a cor de "
          "destaque escolhida, e não dava para corrigir o contraste deles como "
          "corrigimos o do texto.",
          "Cada ícone acompanha a cor do texto ao lado, em qualquer tema."),
         ("Ícone e máquina",
          "O desenho mudava entre Windows, Android e cada navegador. Em fonte antiga, "
          "alguns viravam um retângulo vazio.",
          "O desenho é o mesmo em qualquer lugar, porque vai junto com a página."),
         ("Botões que sumiam",
          "Dois botões ficavam pretos sobre fundo escuro — praticamente invisíveis. O "
          "emoji escondia o problema porque trazia a própria cor.",
          "Corrigido, com verificação automática de contraste."),
     ],
     "RF-328 a RF-335"),

    ("12. Segurança e comportamento interno",
     "Mudanças que o usuário não vê diretamente, mas que protegem os arquivos e "
     "a conta.",
     [
         ("Abrir um arquivo pelo app",
          "O endereço aceitava qualquer caminho do computador.",
          "Só abre arquivos que estejam dentro das pastas que você importou."),
         ("Chave de sessão",
          "Era um valor fixo escrito no código.",
          "Gerada e guardada na primeira vez que o programa roda."),
         ("Atualizações da interface",
          "O navegador guardava a versão antiga em cache e a mudança não aparecia.",
          "Os arquivos da interface não são mais guardados em cache."),
         ("Apagar pastas",
          "—",
          "O servidor recusa apagar qualquer caminho que não esteja registrado para "
          "aquela coleção e aquele usuário, mesmo que exista no disco."),
     ],
     "RF-045 · RF-100 · RF-107 a RF-108 · RF-138 a RF-139"),
]

FORA_DE_ESCOPO = [
        ("Coleções dentro de coleções",
         "Fora de escopo por decisão registrada no planejamento (RF-277). Muda a "
         "estrutura de dados e a navegação inteira; é uma frente própria."),
        ("Remover arquivos duplicados na exportação",
         "Dois itens diferentes da coleção que apontem para arquivos de conteúdo "
         "idêntico são exportados os dois. Comparar conteúdo é uma decisão de produto "
         "que ainda não foi tomada."),
    ]

DECISOES = [
        ("A tecla Esc deveria limpar a busca?",
         "Hoje Esc fecha janelas em todo o app, e usar a mesma tecla para duas "
         "coisas confundiria. O × do campo limpa. Pode mudar depois sem retrabalho."),
        ("Cor dos botões com degradê",
         "Ficaram um tom mais escuros para o texto branco atingir o mínimo de "
         "leitura. Se achar que descaracterizou a marca, dá para reverter — mas o "
         "texto dos botões volta a ficar abaixo do mínimo. É decisão de produto."),
        ("Suporte a outros sistemas",
         "O app é de Windows: usa o Explorer e os seletores de pasta do sistema. "
         "Abrir para Mac e Linux é possível, e fica mais caro quanto mais tarde."),
        ("Testes automatizados da interface",
         "Adicionaria uma ferramenta nova ao projeto, então não fiz por conta "
         "própria. Hoje a interface é conferida manualmente e por checagens "
         "automáticas rodadas no navegador."),
    ]

REFERENCIAS = [
        ("Especificação de cada requisito", "docs/09-requisitos-funcionais.md"),
        ("Desempenho, segurança e limites", "docs/10-requisitos-nao-funcionais.md"),
        ("Endereços que a interface usa", "docs/API.md"),
        ("Como substituir ou mexer na interface", "docs/FRONTEND.md"),
        ("Como rodar os testes", "docs/TESTING.md"),
    ]


def montar(data):
    doc = novo_documento()

    capa(doc,
         "RELATÓRIO DE IMPLEMENTAÇÃO",
         ["Requisitos funcionais entregues", "e o que mudou para quem usa"],
         None,
         data,
         ["338 requisitos · 799 testes automatizados",
          "branch feature/colecoes-organizacao-e-pastas"])

    abrir_miolo(doc)

    doc.add_heading("Como ler este documento", level=1)
    for t in [
        "Este relatório reúne o que foi implementado nas três frentes de trabalho e "
        "descreve cada mudança pelo que ela significa na prática: como era antes e "
        "como ficou. A linguagem é deliberadamente simples, sem termos técnicos.",
        "Cada capítulo termina com os códigos dos requisitos que ele cobre, para quem "
        "quiser rastrear até a especificação. O detalhamento técnico de cada requisito "
        "continua em docs/09-requisitos-funcionais.md, no repositório — este documento "
        "não o repete de propósito, porque 338 linhas de especificação não se leem "
        "como um relato.",
        "As linhas marcadas com “—” na coluna “Como era” são recursos que simplesmente "
        "não existiam antes.",
    ]:
        doc.add_paragraph(t)

    doc.add_heading("Resumo", level=1)
    tabela(doc, ("Indicador", "Número"), RESUMO, (11.5, 4.5),
           negrito_primeira=False)

    for titulo, contexto, linhas, rfs in CAPITULOS:
        doc.add_heading(titulo, level=1)
        doc.add_paragraph(contexto).paragraph_format.keep_with_next = True
        tabela(doc, ("O que mudou", "Como era", "Como é agora"),
               linhas, (3.6, 6.2, 6.2))
        nota(doc, "Requisitos: " + rfs)

    doc.add_heading("O que ficou de fora, e por quê", level=1)
    tabela(doc, ("Item", "Motivo"), FORA_DE_ESCOPO, (4.6, 11.4))

    doc.add_heading("Decisões que ainda dependem de você", level=1)
    doc.add_paragraph(
        "Pontos em aberto por escolha, não por esquecimento. Nenhum bloqueia o "
        "uso do app; todos mudam alguma coisa se você decidir diferente.")
    tabela(doc, ("Questão", "Situação hoje"), DECISOES, (5.0, 11.0))

    doc.add_heading("Onde encontrar o detalhe", level=1)
    tabela(doc, ("Assunto", "Arquivo no repositório"), REFERENCIAS, (7.0, 9.0),
           negrito_primeira=False)

    return salvar(doc, "SearchPlus_Implementacoes", data)


if __name__ == "__main__":
    raiz_do_repositorio()
    for caminho in montar(data_do_argumento(sys.argv)):
        if caminho:
            print(os.path.relpath(caminho).replace("\\", "/"))
