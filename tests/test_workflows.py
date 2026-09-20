"""Os workflows são código que só roda no servidor — pelo menos o YAML se valida aqui.

Workflow inválido não falha um job: o run nasce morto ("startup failure") e é
fácil não perceber que o cron parou de rodar.
"""
import datetime
import glob
import os
import re
import unittest

import yaml

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS = sorted(glob.glob(os.path.join(RAIZ, ".github", "workflows", "*.yml")))


class WorkflowTest(unittest.TestCase):
    def test_existem_workflows(self):
        self.assertGreaterEqual(len(WORKFLOWS), 4, WORKFLOWS)

    def test_cada_workflow_e_yaml_valido_com_nome_gatilho_e_jobs(self):
        for caminho in WORKFLOWS:
            with self.subTest(workflow=os.path.basename(caminho)):
                with open(caminho, encoding="utf-8") as handle:
                    documento = yaml.safe_load(handle)

                self.assertIsInstance(documento, dict)
                self.assertTrue(documento.get("name"), "workflow sem name")
                # `on:` vira True em YAML 1.1 — o GitHub lê a chave, não o booleano.
                self.assertTrue(
                    documento.get("on") or documento.get(True), "workflow sem gatilho"
                )
                self.assertTrue(documento.get("jobs"), "workflow sem jobs")

    def test_todo_step_tem_uses_ou_run(self):
        for caminho in WORKFLOWS:
            with open(caminho, encoding="utf-8") as handle:
                documento = yaml.safe_load(handle)
            for nome_job, job in (documento.get("jobs") or {}).items():
                for indice, step in enumerate(job.get("steps") or []):
                    with self.subTest(workflow=os.path.basename(caminho), job=nome_job):
                        self.assertTrue(
                            step.get("uses") or step.get("run"),
                            f"step #{indice + 1} sem uses nem run",
                        )

    def test_curadoria_commita_midia_junto_dos_candidatos(self):
        """Mídia em branch separada deixaria os links do relatório apontando
        para arquivos que não existem em main."""
        with open(os.path.join(RAIZ, ".github", "workflows", "curate.yml"), encoding="utf-8") as h:
            conteudo = h.read()

        self.assertIn("git add -- queue/candidates.yaml state/catalog.json media/", conteudo)
        self.assertNotIn("git checkout -b", conteudo)


class HeartbeatTest(unittest.TestCase):
    """O heartbeat é o único workflow cuja falha não aparece em lugar nenhum.

    O GitHub desativa os crons de um repositório público depois de 60 dias sem
    atividade. Se o heartbeat pulsar de menos, o repositório atravessa a janela
    e todos os agendados morrem juntos — inclusive o vigia, que é quem deveria
    avisar. Não há alarme para esse caso: o teste é o alarme.
    """

    CAMINHO = os.path.join(RAIZ, ".github", "workflows", "heartbeat.yml")
    # 60 dias é o prazo do GitHub. A folga existe porque o agendador descarta
    # ocorrências: entregou 25% no cron horário, e um pulso marcado não é um
    # pulso dado.
    FOLGA_MAXIMA_DIAS = 14

    def test_o_pulso_cabe_com_folga_na_janela_de_60_dias(self):
        disparos = _dias_de_disparo(self.CAMINHO, dias=60)

        self.assertGreaterEqual(
            len(disparos), 8, "poucas chances de pulso em 60 dias"
        )
        maior_intervalo = max(
            (b - a).days for a, b in zip(disparos, disparos[1:])
        )
        self.assertLessEqual(
            maior_intervalo,
            self.FOLGA_MAXIMA_DIAS,
            "intervalo entre pulsos grande demais para um agendador que descarta ocorrências",
        )

    def test_o_ensaio_nao_reativa_nada(self):
        """Ensaio que mexe em workflow de verdade é pior que ensaio nenhum.

        O ensaio serve para exercitar o caminho que abre a issue — o único que
        só rodaria no dia do problema. Reativar de mentira não testa nada e
        pode desfazer um `disabled_manually` de alguém.
        """
        with open(self.CAMINHO, encoding="utf-8") as handle:
            linhas = handle.read().splitlines()

        guarda = [i for i, l in enumerate(linhas) if 'if [ -z "$ensaio" ]' in l]
        put = [i for i, l in enumerate(linhas) if "gh api -X PUT" in l]
        self.assertTrue(guarda, "o ensaio não está separado da reativação")
        self.assertTrue(put)
        self.assertLess(
            guarda[0], put[0], "a reativação precisa estar dentro da guarda do ensaio"
        )

    def test_so_reativa_o_que_o_github_desativou_por_inatividade(self):
        """Reativar `disabled_manually` desfaria uma decisão de alguém."""
        with open(self.CAMINHO, encoding="utf-8") as handle:
            conteudo = handle.read()

        self.assertTrue(
            'select(.state == "disabled_inactivity")' in conteudo,
            "o filtro precisa pegar só o que o GitHub desativou por inatividade",
        )
        # Reativar é um PUT por id, e o único id que circula é o que saiu do
        # filtro acima. Um PUT com qualquer outra origem reativaria demais.
        puts = [linha for linha in conteudo.splitlines() if "gh api -X PUT" in linha]
        self.assertTrue(puts, "o workflow não reativa nada")
        for linha in puts:
            self.assertIn("${id}/enable", linha, linha)


if __name__ == "__main__":
    unittest.main()


class CommitGuardTest(unittest.TestCase):
    """`git diff` não enxerga arquivo novo — e o job sai verde sem gravar nada.

    Aconteceu de verdade: a primeira curadoria coletou 135 posts, escreveu os
    candidatos e descartou tudo porque os arquivos ainda eram untracked.
    """

    def test_todo_gate_de_commit_compara_o_indice(self):
        for caminho in WORKFLOWS:
            with open(caminho, encoding="utf-8") as handle:
                conteudo = handle.read()
            for linha in conteudo.splitlines():
                if "git diff" in linha and "--quiet" in linha:
                    with self.subTest(workflow=os.path.basename(caminho), linha=linha):
                        self.assertIn(
                            "--cached",
                            linha,
                            "compare o índice (git add antes), senão arquivo novo passa batido",
                        )

    def test_quem_compara_o_indice_estagia_antes(self):
        for caminho in WORKFLOWS:
            with open(caminho, encoding="utf-8") as handle:
                conteudo = handle.read()
            if "git diff --cached" in conteudo:
                with self.subTest(workflow=os.path.basename(caminho)):
                    self.assertIn("git add", conteudo)
                    self.assertLess(
                        conteudo.index("git add"),
                        conteudo.index("git diff --cached"),
                        "o git add precisa vir antes da comparação",
                    )


class CaminhosDeArquivoTest(unittest.TestCase):
    """Renomear arquivo e esquecer o workflow quebra só em produção.

    Aconteceu: a fila virou queue/stories.yaml e o `git add` continuou citando
    queue/drafts.yaml. Os testes passaram; o job caiu com pathspec inválido.
    """

    def test_workflows_citam_os_caminhos_que_o_codigo_usa(self):
        from poster.inbox import DRAFTS_PATH, IMPORTED_PATH
        from poster.queue_file import QUEUE_PATH
        from poster.state import STATE_PATH

        esperados = {
            os.path.relpath(caminho, RAIZ).replace(os.sep, "/")
            for caminho in (DRAFTS_PATH, IMPORTED_PATH, QUEUE_PATH, STATE_PATH)
        }
        citados = set()
        for caminho in WORKFLOWS:
            with open(caminho, encoding="utf-8") as handle:
                conteudo = handle.read()
            for arquivo in esperados | {"queue/drafts.yaml", "queue/candidates.yaml"}:
                if arquivo in conteudo:
                    citados.add(arquivo)

        orfaos = citados - esperados - {"queue/candidates.yaml"}
        self.assertEqual(orfaos, set(), f"workflow cita caminho que não existe: {orfaos}")


def _gatilhos(documento: dict) -> dict:
    # `on:` vira True em YAML 1.1; o GitHub lê a chave, não o booleano.
    bruto = documento.get("on", documento.get(True))
    return bruto if isinstance(bruto, dict) else {}


def _carregar(caminho: str) -> dict:
    with open(caminho, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _inputs_declarados(
    documento: dict, gatilhos: tuple[str, ...] = ("workflow_call", "workflow_dispatch")
) -> set[str]:
    """Inputs declarados, por gatilho.

    O padrão une os dois porque o corpo do workflow pode ser alcançado por
    qualquer um deles. A chamada reutilizável é o caso restrito: o GitHub
    valida `with:` só contra `workflow_call`, e declarar em `workflow_dispatch`
    não conta. Foi essa distinção que deixou o bug do `queue` passar.
    """
    declarados: set[str] = set()
    for gatilho in gatilhos:
        config = _gatilhos(documento).get(gatilho)
        if isinstance(config, dict):
            declarados |= set(config.get("inputs") or {})
    return declarados


class ContratoDeInputsTest(unittest.TestCase):
    """Chamar um workflow reutilizável com input que ele não declara mata o run.

    Foi exatamente o que aconteceu com `queue`: publish.yml usava
    `inputs.queue` sem nunca tê-lo declarado, e o cron de stories nasceu morto
    todos os dias — sem job, sem log, sem e-mail de falha. Testar YAML válido
    não pegava, porque o YAML estava válido.
    """

    def test_todo_input_passado_existe_no_workflow_chamado(self):
        for caminho in WORKFLOWS:
            documento = _carregar(caminho)
            for nome_job, job in (documento.get("jobs") or {}).items():
                usa = str(job.get("uses") or "")
                if not usa.startswith("./"):
                    continue
                alvo = os.path.join(RAIZ, usa.removeprefix("./").split("@")[0])
                with self.subTest(workflow=os.path.basename(caminho), job=nome_job):
                    self.assertTrue(os.path.exists(alvo), f"{usa} não existe")
                    declarados = _inputs_declarados(
                        _carregar(alvo), gatilhos=("workflow_call",)
                    )
                    passados = set((job.get("with") or {}))
                    sobrando = passados - declarados
                    self.assertEqual(
                        sobrando,
                        set(),
                        f"{os.path.basename(caminho)} passa {sorted(sobrando)} para "
                        f"{usa}, que não declara esse input — o run nasce morto",
                    )

    def test_todo_input_referenciado_no_corpo_esta_declarado(self):
        # A outra ponta do mesmo erro: usar `inputs.x` sem declarar x faz o
        # valor chegar vazio e o workflow rodar com o padrão errado, calado.
        padrao = re.compile(r"inputs\.([A-Za-z_][A-Za-z0-9_-]*)")
        for caminho in WORKFLOWS:
            with open(caminho, encoding="utf-8") as handle:
                referenciados = set(padrao.findall(handle.read()))
            if not referenciados:
                continue
            documento = _carregar(caminho)
            with self.subTest(workflow=os.path.basename(caminho)):
                faltando = referenciados - _inputs_declarados(documento)
                self.assertEqual(
                    faltando,
                    set(),
                    f"{os.path.basename(caminho)} usa inputs.{sorted(faltando)} "
                    "sem declarar",
                )


def _campo_cron(campo: str, valor: int) -> bool:
    """Casa um campo de cron com um valor. Cobre `*`, listas, faixas e passos.

    Não é um croniter: só o suficiente para conferir cadência de agenda, que é
    o que os testes daqui precisam saber.
    """
    if campo == "*":
        return True
    for parte in campo.split(","):
        passo = 1
        if "/" in parte:
            parte, texto_passo = parte.split("/", 1)
            passo = int(texto_passo)
        if parte == "*":
            if valor % passo == 0:
                return True
            continue
        if "-" in parte:
            inicio, fim = (int(x) for x in parte.split("-", 1))
        else:
            inicio = fim = int(parte)
        if inicio <= valor <= fim and (valor - inicio) % passo == 0:
            return True
    return False


def _dias_de_disparo(caminho: str, *, dias: int) -> list[datetime.date]:
    """Dias em que a agenda do workflow dispara, a partir de hoje.

    Dia do mês e dia da semana são OU quando os dois estão restritos — é a
    regra do cron, e ignorá-la subestimaria a cadência.
    """
    agenda = _gatilhos(_carregar(caminho)).get("schedule") or []
    hoje = datetime.date.today()
    disparos = []
    for salto in range(dias):
        dia = hoje + datetime.timedelta(days=salto)
        # cron usa 0-6 com domingo em 0; date.weekday() usa segunda em 0.
        dow = (dia.weekday() + 1) % 7
        for entrada in agenda:
            _, _, dom, mes, semana = entrada["cron"].split()
            if not _campo_cron(mes, dia.month):
                continue
            if dom == "*" or semana == "*":
                casou = _campo_cron(dom, dia.day) and _campo_cron(semana, dow)
            else:
                casou = _campo_cron(dom, dia.day) or _campo_cron(semana, dow)
            if casou:
                disparos.append(dia)
                break
    return disparos


class HorarioDosStoriesTest(unittest.TestCase):
    """Os crons de story são um experimento de horário — o horário é o dado.

    Um cron escrito em UTC é fácil de mexer errado: trocar a hora e esquecer de
    somar as 3h desloca o experimento sem quebrar nada visível. Este teste fixa
    a conversão, para que a mudança apareça aqui e não nos números do mês que vem.
    """

    # Horários de DISPARO, adiantados ~4h porque o cron deste repositório
    # atrasa de 3h20 a 5h24. O story sai entre 11h54-14h e 15h54-18h.
    DISPAROS_BRT = {(8, 34), (12, 34)}

    def test_os_crons_caem_nos_horarios_combinados(self):
        caminho = os.path.join(RAIZ, ".github", "workflows", "publicar-stories-auto.yml")
        agenda = _gatilhos(_carregar(caminho)).get("schedule") or []

        disparos = set()
        for entrada in agenda:
            minuto, hora = entrada["cron"].split()[:2]
            # São Paulo é UTC-3 fixo: sem horário de verão desde 2019.
            disparos.add(((int(hora) - 3) % 24, int(minuto)))

        self.assertEqual(disparos, self.DISPAROS_BRT)
