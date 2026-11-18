# Nightly database backups (step 6.5, ADR-023), off the server: the data volume survives a
# spot replacement, but not a `terraform destroy`, a broken disk or a bad migration.
#
# The server writes a pg_dump here every night (user-data.sh.tftpl, sa-backup.timer) and
# can do nothing else with it: no read, no list, no delete. If the server is ever taken
# over, the attacker cannot read old backups or wipe them; an overwrite only adds a
# version, kept like the rest. Only the owner's admin login may read them, to restore
# (README.md). The dumps hold every user's data, with Google tokens still encrypted by the
# gateway's key (invariant 1), which is not in the bucket.

resource "aws_s3_bucket" "backups" {
  bucket = "sa-backups-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "backups" {
  bucket                  = aws_s3_bucket.backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "backups" {
  bucket = aws_s3_bucket.backups.id
  versioning_configuration {
    status = "Enabled"
  }
}

#trivy:ignore:AWS-0132 S3-managed keys: a customer key costs $1 a month, and only one login can read (ADR-023)
resource "aws_s3_bucket_server_side_encryption_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# 14 days of backups (decided 18.11), overwritten versions included; a half-finished
# upload is cleaned up after a day.
resource "aws_s3_bucket_lifecycle_configuration" "backups" {
  bucket = aws_s3_bucket.backups.id
  rule {
    id     = "keep-14-days"
    status = "Enabled"
    filter {}
    expiration {
      days = 14
    }
    noncurrent_version_expiration {
      noncurrent_days = 14
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

data "aws_iam_policy_document" "backups_bucket" {
  # TLS only.
  statement {
    sid       = "TlsOnly"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.backups.arn, "${aws_s3_bucket.backups.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
  # Reading a backup is the owner's admin login only. Other roles in the account have broad
  # read rights (CI's plan role has ReadOnlyAccess); this deny wins over all of them.
  statement {
    sid       = "ReadOnlyByTheOwner"
    effect    = "Deny"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.backups.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "ArnNotLike"
      variable = "aws:PrincipalArn"
      values   = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/aws-reserved/sso.amazonaws.com/*/AWSReservedSSO_AdministratorAccess_*"]
    }
  }
}

resource "aws_s3_bucket_policy" "backups" {
  bucket = aws_s3_bucket.backups.id
  policy = data.aws_iam_policy_document.backups_bucket.json
  # The public access block first, so the policy is never briefly checked without it.
  depends_on = [aws_s3_bucket_public_access_block.backups]
}

# The server: write new backups, nothing else.
data "aws_iam_policy_document" "write_backups" {
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.backups.arn}/postgres/*"]
  }
}

resource "aws_iam_role_policy" "write_backups" {
  name   = "write-backups"
  role   = aws_iam_role.server.id
  policy = data.aws_iam_policy_document.write_backups.json
}
