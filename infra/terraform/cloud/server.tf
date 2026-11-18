# The server (Layer 6, step 6.2, ADR-023): one spot instance in an Auto Scaling group of one.
#
# Spot capacity can be taken back with two minutes' notice. The group then starts another
# instance, which takes over the same Elastic IP and the same data volume, so k3s comes back
# as the same cluster with the same data. The cost of an interruption is a few minutes.
#
# To stop every charge: `terraform destroy` in this directory (README.md). Stopping the
# instance alone keeps paying for the disk and the IP.

data "aws_caller_identity" "current" {}

resource "aws_eip" "server" {
  domain = "vpc"
  tags   = { Name = "scheduling-agent" }
}

resource "aws_ebs_volume" "data" {
  availability_zone = var.availability_zone
  size              = var.data_volume_gib
  type              = "gp3"
  encrypted         = true #trivy:ignore:AWS-0027 AWS-managed key: a customer key costs extra (ADR-023)
  tags              = { Name = "scheduling-agent-data" }
}

# --- What the server may do ---------------------------------------------------------------

data "aws_iam_policy_document" "assume_ec2" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "server" {
  name               = "scheduling-agent-server"
  assume_role_policy = data.aws_iam_policy_document.assume_ec2.json
}

# Session Manager instead of SSH: access is logged and goes through the owner's AWS login.
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.server.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# At boot the server takes over its address and its data volume, and nothing else.
data "aws_iam_policy_document" "self_heal" {
  statement {
    actions   = ["ec2:DescribeVolumes", "ec2:DescribeAddresses"]
    resources = ["*"] # describe calls cannot be limited to a resource
  }
  statement {
    actions = ["ec2:AttachVolume"]
    resources = [
      aws_ebs_volume.data.arn,
      "arn:aws:ec2:${var.region}:${data.aws_caller_identity.current.account_id}:instance/*",
    ]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/project"
      values   = ["scheduling-agent"]
    }
  }
  statement {
    actions = ["ec2:AssociateAddress"]
    resources = [
      "arn:aws:ec2:${var.region}:${data.aws_caller_identity.current.account_id}:elastic-ip/${aws_eip.server.allocation_id}",
      "arn:aws:ec2:${var.region}:${data.aws_caller_identity.current.account_id}:instance/*",
      "arn:aws:ec2:${var.region}:${data.aws_caller_identity.current.account_id}:network-interface/*",
    ]
  }
}

resource "aws_iam_role_policy" "self_heal" {
  name   = "take-over-address-and-data"
  role   = aws_iam_role.server.id
  policy = data.aws_iam_policy_document.self_heal.json
}

resource "aws_iam_instance_profile" "server" {
  name = "scheduling-agent-server"
  role = aws_iam_role.server.name
}

# --- The instance -------------------------------------------------------------------------

resource "aws_launch_template" "server" {
  name_prefix   = "scheduling-agent-"
  image_id      = var.ami_id
  instance_type = var.instance_types[0]
  user_data = base64encode(templatefile("${path.module}/user-data.sh.tftpl", {
    region         = var.region
    volume_id      = aws_ebs_volume.data.id
    eip_allocation = aws_eip.server.allocation_id
    k3s_version    = var.k3s_version
    k3s_sha256     = var.k3s_sha256
  }))

  iam_instance_profile {
    arn = aws_iam_instance_profile.server.arn
  }

  network_interfaces {
    subnet_id                   = aws_subnet.public.id
    security_groups             = [aws_security_group.server.id]
    associate_public_ip_address = true # only until the Elastic IP is taken over at boot
    delete_on_termination       = true
  }

  # IMDSv2 only, one hop: a pod cannot reach the instance's credentials through a proxy.
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  # A t4g runs at 20% of each core and spends credits above that. "unlimited" (the default
  # for t4g) bills the extra when credits run out; "standard" slows the server down instead,
  # so a busy hour can never raise the bill. Non-burstable fallback types ignore this.
  credit_specification {
    cpu_credits = "standard"
  }

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = 10
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name       = "scheduling-agent"
      project    = "scheduling-agent"
      managed-by = "terraform"
    }
  }
}

resource "aws_autoscaling_group" "server" {
  name                = "scheduling-agent"
  min_size            = 1
  max_size            = 1
  desired_capacity    = 1
  vpc_zone_identifier = [aws_subnet.public.id]
  health_check_type   = "EC2"
  # Start a replacement as soon as AWS warns that a spot instance is at risk.
  capacity_rebalance = true

  mixed_instances_policy {
    instances_distribution {
      on_demand_base_capacity                  = 0
      on_demand_percentage_above_base_capacity = 0
      spot_allocation_strategy                 = "price-capacity-optimized"
    }
    launch_template {
      launch_template_specification {
        launch_template_id = aws_launch_template.server.id
        version            = aws_launch_template.server.latest_version
      }
      dynamic "override" {
        for_each = var.instance_types
        content {
          instance_type = override.value
        }
      }
    }
  }

  # A changed launch template rolls the server: the old one goes, the new one takes over.
  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 0
    }
  }

  tag {
    key                 = "project"
    value               = "scheduling-agent"
    propagate_at_launch = true
  }
}
