# Modelo de custo — como os números do showback são calculados

## O que é medido de verdade vs. o que é estimado

O `countconnector` do Collector mede **contagem de registros** roteados por
`service.name`/`team`/`cost_center`/`telemetry.tier` — isso é medição real,
exposta em `:8888`/`:8889` e raspada pelo Prometheus. **Não é medição de
bytes de rede ou disco.**

Para converter contagem em GB estimado (necessário para expressar custo em
USD), usamos um tamanho médio por tipo de sinal, definido em
`policy-compiler/compile.py::BYTES_PER_RECORD`:

| Sinal | Bytes/registro (estimado) |
|---|---|
| logs | 256 |
| spans (traces) | 512 |
| datapoints (métricas) | 64 |

Estes números são **aproximações documentadas**, não uma medição precisa de
payload serializado. Para uma demo/portfólio isso é aceitável e é dito
explicitamente aqui e no artigo — a metodologia de roteamento por valor não
depende de precisão de bytes, só de proporção relativa entre serviços/tiers.
Em produção, o ideal seria instrumentar o exporter para relatar bytes reais
(algumas versões recentes do Collector expõem métricas de tamanho de
payload por exporter).

## Constantes de custo

`COST_PER_GB_HOT` (padrão 0.50 USD/GB) e `COST_PER_GB_WARM` (padrão 0.023
USD/GB) — a segunda é próxima do preço público de S3 Standard; a primeira é
uma aproximação de custo de ingestão de uma plataforma de observabilidade
comercial paga por volume. Ajustáveis via `.env` e via flags do
`policy-compiler` (`--cost-per-gb-hot`/`--cost-per-gb-warm`).

## As três métricas de showback

- **`cost:residual_usd:by_service_tier`** — o que ainda é pago (hot + warm).
- **`cost:downgrade_saving_usd:by_service`** — volume que foi para warm em
  vez de hot, multiplicado pela diferença de preço. **Simplificação
  deliberada**: isso mistura "reclassificação verdadeira" (um sinal que
  seria hot mas foi rebaixado) com "base natural warm" (um sinal que nunca
  seria hot, ex.: log INFO de serviço standard). Não separamos as duas
  porque exigiria rastrear a decisão contrafactual "o que teria acontecido
  sem a regra X" — fora do escopo da demo, mas documentado aqui para quem
  for adaptar isso para uma implementação real.
- **`cost:drop_saving_usd:by_service`** — volume descartado × custo hot
  (economia total, sem simplificação — descartado é descartado).

## Custo de consulta (Athena) — por que particionamento importa

Athena cobra por TB **escaneado**, não por tempo de query. A tabela Glue
(`terraform/modules/glue-catalog`) particiona por `cost_center`/`dt`/
`service_name` justamente para que uma pergunta como "logs do checkout-api
em 07/09" escaneie só a partição relevante, não o bucket inteiro. Um warm
tier sem particionamento correto é uma armadilha comum: a economia de
ingestão é destruída pelo custo de cada consulta subsequente.
