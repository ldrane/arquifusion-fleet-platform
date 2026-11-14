# Publicar aquí (y en SSM /arquifusion/<stage>/...) lo que otros stacks necesitan.

output "api_lectura_function_name" {
  value = aws_lambda_function.api_lectura.function_name
}

output "api_lectura_invoke_arn" {
  value = aws_lambda_function.api_lectura.invoke_arn
}
