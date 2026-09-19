"""Os workflows são código que só roda no servidor — pelo menos o YAML se valida aqui.

Workflow inválido não falha um job: o run nasce morto ("startup failure") e é
fácil não perceber que o cron parou de rodar.
"""
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


class HorarioDosStoriesTest(unittest.TestCase):
    """Os crons de story são um experimento de horário — o horário é o dado.

    Um cron escrito em UTC é fácil de mexer errado: trocar a hora e esquecer de
    somar as 3h desloca o experimento sem quebrar nada visível. Este teste fixa
    a conversão, para que a mudança apareça aqui e não nos números do mês que vem.
    """

    HORARIOS_BRT = {18, 21}

    def test_os_crons_caem_nos_horarios_combinados(self):
        caminho = os.path.join(RAIZ, ".github", "workflows", "publicar-stories-auto.yml")
        agenda = _gatilhos(_carregar(caminho)).get("schedule") or []

        horas_brt = set()
        for entrada in agenda:
            minuto, hora = entrada["cron"].split()[:2]
            self.assertEqual(minuto, "0", f"cron fora da hora cheia: {entrada['cron']}")
            # São Paulo é UTC-3 fixo: sem horário de verão desde 2019.
            horas_brt.add((int(hora) - 3) % 24)

        self.assertEqual(horas_brt, self.HORARIOS_BRT)
