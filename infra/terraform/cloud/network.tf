# One public subnet in one zone (ADR-023). No NAT gateway: it costs more than the server.
# The server has a public address, and the security group lets in HTTP and HTTPS only.

resource "aws_vpc" "main" {
  cidr_block           = "10.20.0.0/16"
  enable_dns_hostnames = true
  tags                 = { Name = "scheduling-agent" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "scheduling-agent" }
}

resource "aws_subnet" "public" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.20.1.0/24"
  availability_zone = var.availability_zone
  # The server gets the Elastic IP; no automatic, changing public address.
  map_public_ip_on_launch = false
  tags                    = { Name = "scheduling-agent-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "scheduling-agent-public" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# The VPC's default security group allows all traffic between its members; take that away,
# so only the group below is ever in use.
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.main.id
}

resource "aws_security_group" "server" {
  name        = "scheduling-agent-server"
  description = "HTTP for the certificate challenge, HTTPS for Meta, Google and the owner"
  vpc_id      = aws_vpc.main.id

  # No SSH: the owner reaches the server through SSM Session Manager.
  ingress {
    description = "HTTP: Lets Encrypt challenges, then a redirect to HTTPS"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] #trivy:ignore:AWS-0107 public by design: Meta and Google call in
  }
  ingress {
    description = "HTTPS: web app, API, Meta webhook and Google callback"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] #trivy:ignore:AWS-0107 public by design: Meta and Google call in
  }
  egress {
    description = "Out to the internet: Google, Meta, Anthropic, GitHub, image registries"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"] #trivy:ignore:AWS-0104 egress is limited per pod by NetworkPolicies
  }
}
