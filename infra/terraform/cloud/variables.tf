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
    4 GiB ARM types, cheapest first. The system uses about 3 GiB (measured on k3d, 18.11).
    More than one type gives spot more pools to choose from when one runs out.
  EOT
  type        = list(string)
  default     = ["t4g.medium", "m7g.medium"]
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
