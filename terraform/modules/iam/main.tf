# Duas identidades separadas por princípio de menor privilégio:
#   - otel-gateway-collector: só escreve no warm tier (nunca lê, nunca lista)
#   - otel-cost-governance-reader: só lê/consulta (times de produto consultando
#     seus próprios dados via Athena) — nunca escreve
#
# Trust policy abaixo é um placeholder genérico (assume-role via conta atual).
# Em produção com EKS, isto seria IRSA:
#
# data "aws_iam_policy_document" "collector_trust_irsa" {
#   statement {
#     effect  = "Allow"
#     actions = ["sts:AssumeRoleWithWebIdentity"]
#     principals {
#       type        = "Federated"
#       identifiers = [var.eks_oidc_provider_arn]
#     }
#     condition {
#       test     = "StringEquals"
#       variable = "${var.eks_oidc_provider_url}:sub"
#       values   = ["system:serviceaccount:observability:otel-gateway-collector"]
#     }
#   }
# }

data "aws_iam_policy_document" "collector_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::*:root"] # placeholder — restringir à conta real em produção
    }
  }
}

resource "aws_iam_role" "collector" {
  name               = var.role_name
  assume_role_policy = data.aws_iam_policy_document.collector_trust.json
}

data "aws_iam_policy_document" "collector_write" {
  statement {
    sid       = "WriteWarmTierOnly"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${var.warm_tier_bucket_arn}/otel/*"]
  }
}

resource "aws_iam_policy" "collector_write" {
  name   = "${var.role_name}-write-warm-tier"
  policy = data.aws_iam_policy_document.collector_write.json
}

resource "aws_iam_role_policy_attachment" "collector_write" {
  role       = aws_iam_role.collector.name
  policy_arn = aws_iam_policy.collector_write.arn
}

data "aws_iam_policy_document" "reader" {
  statement {
    sid    = "ReadProcessedData"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = [
      var.warm_tier_bucket_arn,
      "${var.warm_tier_bucket_arn}/processed/*",
    ]
  }

  statement {
    sid    = "WriteQueryResultsOnly"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
    ]
    resources = ["${var.athena_results_bucket_arn}/athena-results/*"]
  }

  statement {
    sid    = "AthenaQuery"
    effect = "Allow"
    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:StopQueryExecution",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "GlueCatalogRead"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetTable",
      "glue:GetPartitions",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "reader" {
  name   = "otel-cost-governance-reader"
  policy = data.aws_iam_policy_document.reader.json
}
