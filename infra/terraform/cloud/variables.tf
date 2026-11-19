variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "availability_zone" {
  description = <<-EOT
    One zone for everything: an EBS volume lives in one zone, and every replacement server
    must be able to attach the same data volume. Chosen for the lowest spot price on 18.11.
  EOT
  type        = string
  default     = "eu-central-1b"
}

variable "instance_types" {
  description = <<-EOT
    4 GiB ARM types with a full core, no CPU credits. The system uses about 3 GiB.
    Not t4g: this account cannot run burstable types in "unlimited" mode, and in "standard"
    mode a new spot server starts with no credits, gets 20% of each core, and k3s fails to
    start (seen 18.11). More than one type gives spot more pools when one runs out.
  EOT
  type        = list(string)
  default     = ["m6g.medium", "m8g.medium"]
}

variable "spot_max_price" {
  description = <<-EOT
    The most an hour may cost, in USD. Spot is billed at the market price, not at this cap;
    when the market price rises above the cap, AWS takes the server back. $0.03 sat right
    above the market (m6g $0.0277, m8g $0.0299 on 19.11), so small rises moved the server.
    $0.035 leaves room: about $26 a month for the server at most, about $32 with the disks and
    the address, while a normal month stays at the market price (about $24-27 in all).
  EOT
  type        = string
  default     = "0.035"
}

variable "ami_id" {
  description = <<-EOT
    Amazon Linux 2023 for arm64, pinned so a new image is a reviewed change, not a surprise
    replacement. It has the SSM agent built in, so the server needs no SSH. From
    /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64.
  EOT
  type        = string
  default     = "ami-05d7f3394b2c92150" # al2023-ami-2023.12.20261117.0-kernel-6.18-arm64
}

variable "k3s_version" {
  description = "The same minor version as k3d, released at least two weeks ago (T20)."
  type        = string
  default     = "v1.35.10+k3s1"
}

variable "k3s_sha256" {
  description = "SHA-256 of k3s-arm64 from that release's sha256sum-arm64.txt."
  type        = string
  default     = "0c780ef4b6275bd27c77ed64a647fa1d859b1bd60597ad420f3243c261e5ffb6"
}

variable "data_volume_gib" {
  description = "k3s's whole state lives here: images, the database's volume, Sealed Secrets' key."
  type        = number
  default     = 20
}
