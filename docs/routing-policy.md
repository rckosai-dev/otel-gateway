# Política de roteamento — como a decisão é tomada

Fonte de verdade: `policy/routing-policy.yaml` + `policy/service-catalog.yaml`
+ `policy/cost-budget.yaml`. Compilado por `policy-compiler/compile.py` em
OTTL (ver `docs/architecture.md`). Este documento explica o *porquê* de cada
regra, na ordem em que são avaliadas (primeira regra que casa decide).

## 1. Override de compliance/retenção legal

Serviços com `compliance_hold: true` no catálogo (ex.: `payment-gateway`,
`auth-service`) sempre vão para `warm`, **nunca** `drop`, independente de
tier, erro ou orçamento. Isso é inegociável em qualquer empresa real com
obrigação de auditoria — a política tem que expressar isso explicitamente,
não como uma exceção manual.

## 2. Upgrade por severidade/relevância de SLO

Um sinal de erro (log `ERROR`/`FATAL`, span com `status.code=ERROR` ou
`http.status_code >= 500`, métrica SLO-relevante) sobe um nível:

| Tier do serviço | Decisão base | Com erro/SLO-relevante |
|---|---|---|
| critical | warm | **hot** |
| standard | warm | **hot** |
| low | drop | **warm** |

Isso é o núcleo do argumento "sem perder fidelidade de SLO": mesmo um
serviço `low`-tier tem seus erros preservados (viram warm, não são
descartados) — só o ruído de baixo valor (DEBUG/INFO sem erro) é candidato a
drop.

## 3. Classificação base por tier de criticidade

Sem erro/SLO-relevância, a decisão vem só da criticidade do serviço no
catálogo: `critical`/`standard` → `warm`; `low` → `drop`. Note que **nem
todo sinal de um serviço crítico vai para hot** — isso é deliberado: hot é
caro, e a maior parte do tráfego "normal" de um serviço crítico (sem erro,
sem SLO em risco) não precisa de latência de consulta de segundos nem de
retenção cara.

## 4. Downgrade dinâmico por pressão de orçamento

Se o volume de um serviço nas últimas `window` (padrão 1h, ver
`policy/cost-budget.yaml`) ultrapassa `budget_gb`, sinais não-críticos
daquele serviço descem um nível (hot→warm, warm→drop) até normalizar —
exceto sinais de erro, que nunca descem por pressão de orçamento. É um
circuit breaker de custo: a política reage a pressão de volume real, não só
a regras estáticas — o mesmo princípio por trás de sampling adaptativo usado
por plataformas de observabilidade comerciais.

## Exemplos concretos (services.yaml da demo)

- `checkout-api` (critical, error_rate 5%): a maior parte hot (erro alto +
  crítico), volume alto — bom exemplo de "custo residual concentrado onde
  importa".
- `recommendation-engine` (low, altíssimo volume): quase tudo warm/drop —
  principal fonte de "economia evitada" no dashboard.
- `payment-gateway` (critical + compliance_hold): nunca dropado, mesmo que
  estoure budget — demonstra a regra 1 na prática.

## Limitação conhecida deste modelo

A matriz é avaliada de forma determinística e estática por compilação — o
downgrade dinâmico (regra 4) só é reavaliado quando alguém roda
`make recompile-policy-with-budget`. Isso é aceitável para uma demo e é
exatamente a lacuna que o roadmap de OpAMP (`docs/architecture.md`) resolve
em produção.
