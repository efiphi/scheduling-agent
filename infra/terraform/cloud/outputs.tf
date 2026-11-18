output "public_ip" {
  description = "The server's fixed address, for the DNS record (step 6.4)."
  value       = aws_eip.server.public_ip
}

output "data_volume_id" {
  value = aws_ebs_volume.data.id
}
