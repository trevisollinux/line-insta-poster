"""Os workflows são código que só roda no servidor — pelo menos o YAML se valida aqui.

Workflow inválido não falha um job: o run nasce morto ("startup failure") e é
fácil não perceber que o cron parou de rodar.
"""
import glob
import os
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

    def test_arquivo_do_corpo_do_pr_de_curadoria_existe(self):
        self.assertTrue(
            os.path.exists(os.path.join(RAIZ, ".github", "CURADORIA_PR.md")),
            "curate.yml usa --body-file .github/CURADORIA_PR.md",
        )


if __name__ == "__main__":
    unittest.main()
