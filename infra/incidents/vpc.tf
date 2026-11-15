# TAREA-16: VPC aislada (gratis) solo para la Lambda `auditoria`, que habla exclusivamente con DynamoDB.
# Sin NAT ni Internet Gateway: 2 subredes privadas + Gateway Endpoint de DynamoDB. `auditoria` solo usa DynamoDB
# (audit-events + incidents), así que puede vivir aquí sin salir a Internet. El resto de Lambdas queda fuera
# de la VPC porque llaman a Step Functions, SNS y GCP (no hay NAT).
#
# Costo: 0 USD. `aws_vpc`, subredes, route table y el Gateway Endpoint de DynamoDB son gratuitos; solo se
# pagaría el tráfico de datos del endpoint (despreciable aquí).

data "aws_ec2_managed_prefix_list" "dynamodb" {
  name = "com.amazonaws.${var.aws_region}.dynamodb"
}

resource "aws_vpc" "audit" {
  cidr_block           = "10.20.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "${local.prefix}-vpc-audit", owner = "B", rf = "RNF-15 TRZ-02" }
}

resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.audit.id
  cidr_block        = "10.20.1.0/24"
  availability_zone = "${var.aws_region}a"
  tags              = { Name = "${local.prefix}-audit-private-a", owner = "B" }
}

resource "aws_subnet" "private_b" {
  vpc_id            = aws_vpc.audit.id
  cidr_block        = "10.20.2.0/24"
  availability_zone = "${var.aws_region}b"
  tags              = { Name = "${local.prefix}-audit-private-b", owner = "B" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.audit.id
  tags   = { Name = "${local.prefix}-audit-private", owner = "B" }
}

resource "aws_route_table_association" "private_a" {
  subnet_id      = aws_subnet.private_a.id
  route_table_id = aws_route_table.private.id
}

resource "aws_route_table_association" "private_b" {
  subnet_id      = aws_subnet.private_b.id
  route_table_id = aws_route_table.private.id
}

# Gateway Endpoint: el tráfico a DynamoDB no sale a Internet y no cuesta (a diferencia de un endpoint de interfaz).
resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = aws_vpc.audit.id
  service_name      = "com.amazonaws.${var.aws_region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
  tags              = { Name = "${local.prefix}-audit-dynamodb", owner = "B" }
}

# Sin ingress (la Lambda inicia la conexión); el único egress permitido es HTTPS hacia el prefix list de DynamoDB.
resource "aws_security_group" "lambda_data" {
  name        = "${local.prefix}-sg-lambda-data"
  description = "egress 443 solo a DynamoDB (TAREA-16)"
  vpc_id      = aws_vpc.audit.id
  tags        = { Name = "${local.prefix}-sg-lambda-data", owner = "B" }
}

resource "aws_vpc_security_group_egress_rule" "dynamodb_https" {
  security_group_id = aws_security_group.lambda_data.id
  description       = "HTTPS al prefix list de DynamoDB"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  prefix_list_id    = data.aws_ec2_managed_prefix_list.dynamodb.id
  tags              = { Name = "${local.prefix}-audit-dynamodb-egress", owner = "B" }
}

# Flow Logs opcional (apagado por defecto): el Learner Lab no deja crear roles y `aws_flow_log` necesita un rol
# asumible por vpc-flow-logs.amazonaws.com. Ver variable `vpc_flow_logs`.
resource "aws_cloudwatch_log_group" "vpc_flow" {
  count             = var.vpc_flow_logs ? 1 : 0
  name              = "/aws/vpc/${local.prefix}-audit"
  retention_in_days = 7
  tags              = { owner = "B", rf = "RNF-15" }
}

resource "aws_flow_log" "audit" {
  count           = var.vpc_flow_logs ? 1 : 0
  vpc_id          = aws_vpc.audit.id
  traffic_type    = "ALL"
  iam_role_arn    = data.aws_iam_role.lab.arn
  log_destination = aws_cloudwatch_log_group.vpc_flow[0].arn
  tags            = { Name = "${local.prefix}-audit-flow-log", owner = "B" }
}
