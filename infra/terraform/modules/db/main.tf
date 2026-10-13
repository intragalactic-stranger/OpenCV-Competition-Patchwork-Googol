# Defect register: Aurora PostgreSQL Serverless v2 + PostGIS, reached only through the RDS Data API
# (HTTPS, IAM-authenticated): no inbound ports, no NAT, no bastion. Scales to 0 ACU and auto-pauses
# when idle, so it consumes credits only while the pipeline or viewer is using it (decision D-27).

variable "name" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "engine_version" {
  type    = string
  default = "17.6"
}
variable "max_acu" {
  type    = number
  default = 4
}

resource "aws_db_subnet_group" "this" {
  name       = "${var.name}-db"
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "db" {
  name        = "${var.name}-db"
  description = "Aurora: no inbound rules (Data API only)"
  vpc_id      = var.vpc_id
}

resource "aws_rds_cluster" "this" {
  cluster_identifier          = "${var.name}-register"
  engine                      = "aurora-postgresql"
  engine_mode                 = "provisioned"
  engine_version              = var.engine_version
  database_name               = "patchwork"
  master_username             = "patchwork_admin"
  manage_master_user_password = true
  enable_http_endpoint        = true # RDS Data API
  db_subnet_group_name        = aws_db_subnet_group.this.name
  vpc_security_group_ids      = [aws_security_group.db.id]
  storage_encrypted           = true
  backup_retention_period     = 1
  skip_final_snapshot         = true
  deletion_protection         = false
  copy_tags_to_snapshot       = true

  serverlessv2_scaling_configuration {
    min_capacity             = 0
    max_capacity             = var.max_acu
    seconds_until_auto_pause = 600
  }
}

resource "aws_rds_cluster_instance" "writer" {
  identifier          = "${var.name}-register-1"
  cluster_identifier  = aws_rds_cluster.this.id
  instance_class      = "db.serverless"
  engine              = aws_rds_cluster.this.engine
  engine_version      = aws_rds_cluster.this.engine_version
  publicly_accessible = false
}

output "cluster_arn" { value = aws_rds_cluster.this.arn }
output "secret_arn" { value = aws_rds_cluster.this.master_user_secret[0].secret_arn }
output "database" { value = aws_rds_cluster.this.database_name }
