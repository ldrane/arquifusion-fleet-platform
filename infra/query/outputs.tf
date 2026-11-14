# Lo que otros stacks necesitan va también a SSM (/arquifusion/<stage>/query/...), ver main.tf.

output "api_lectura_function_name" {
  value = aws_lambda_function.fn["api_lectura"].function_name
}

output "api_lectura_invoke_arn" {
  value = aws_lambda_function.fn["api_lectura"].invoke_arn
}

output "replicar_function_name" {
  value = aws_lambda_function.fn["replicar"].function_name
}

output "replicar_dlq_url" {
  value = aws_sqs_queue.replicar_dlq.url
}
