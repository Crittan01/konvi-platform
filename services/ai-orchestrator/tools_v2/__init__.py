"""Handlers de function calls — ejecutan los tools que el LLM pide invocar.

Cada handler es una función pura ``(context, args) -> dict`` (o async). Devuelve
el resultado serializable que se envía de vuelta al LLM como
``function_response`` para que componga la respuesta final al cliente.

Diseño:
  - Sin lógica de FSM aquí — eso vive en specialists/coordinator.
  - I/O aislado en repos inyectados (no se acceden globales).
  - Excepciones tipadas (:class:`core.exceptions.ToolExecutionError`).
"""
