# Terraform — retenção como código

Este diretório descreve a infraestrutura real de produção do warm tier
(S3 + Glue + Athena + IAM), a mesma arquitetura que o `docker-compose.yml`
simula localmente com MinIO. **Não é aplicado neste repositório/sandbox.**

## O que roda aqui, e o que não roda

| Comando | Roda no sandbox de demo? | Requer credenciais AWS reais? |
|---|---|---|
| `terraform fmt -check -recursive` | Sim | Não |
| `terraform init -backend=false` | Sim | Não |
| `terraform validate` | Sim | Não |
| `terraform plan` | Não (sem credenciais no ambiente) | Sim |
| `terraform apply` | **Nunca aqui** | Sim |

`make validate-terraform` (raiz do repo) roda os três primeiros. Para rodar
`plan`/`apply` de verdade, use suas próprias credenciais AWS localmente:

```bash
cd terraform
terraform init
terraform plan -var-file=environments/sandbox-plan-only/terraform.tfvars
```

## Por que os nomes de bucket em `environments/sandbox-plan-only/` são "fake"

Nomes de bucket S3 são globalmente únicos. Os valores em
`terraform.tfvars` são só placeholders para validação de sintaxe — troque
por nomes reais (e prováveis nomes já reservados por outra conta) antes de
rodar `plan`/`apply` de verdade.

## Como isso se conecta ao resto do projeto

- `modules/s3-warm-tier`: o mesmo bucket que o `awss3exporter` do Collector
  escreve localmente no MinIO (`docker-compose.yml`), aqui como S3 real.
- `modules/glue-catalog` + `modules/athena`: schema e queries de exemplo
  para o mesmo padrão de consulta validado localmente com `duckdb`
  (ver `scripts/check-minio-parquet.py` e `docs/runbook.md`).
- `modules/iam`: separa a identidade de escrita (Collector) da identidade de
  leitura (times consultando seus dados) — princípio de menor privilégio.

## Limitação conhecida

`terraform fmt -check -recursive` e `terraform init -backend=false` foram
rodados neste ambiente (`fmt` passou, formatação já corrigida). `terraform
validate` **não pôde ser executado aqui**: a política de rede do sandbox
bloqueia `registry.terraform.io` (necessário para baixar o provider
`hashicorp/aws`), então `terraform init` falha antes de chegar em `validate`.
A sintaxe dos módulos foi revisada manualmente contra o schema documentado
do provider AWS ~> 5.0, mas rode `terraform validate` localmente (com acesso
normal à internet) antes de confiar cegamente nela.
