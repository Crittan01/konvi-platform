"""Capa LLM aislada — wrapper Gemini + declaración de tools + parsers.

Diseño:
  - :mod:`tool_specs`  declara los ``FunctionDeclaration`` por dominio (catalog,
    cart, customer_data, shipping, escalation). Son data, no lógica.
  - :mod:`client`      envuelve ``google-genai`` con un único punto de entrada
    ``invoke_llm(...)`` que aplica system_instruction + tool_config + maneja
    ``finishReason``.
  - :mod:`parsers`     traduce la respuesta del modelo (function_call o text)
    a dataclasses tipados que los specialists consumen.

Referencias oficiales:
  - https://ai.google.dev/gemini-api/docs/function-calling
  - https://ai.google.dev/api/generate-content (FinishReason enum)
  - https://ai.google.dev/gemini-api/docs/text-generation (system_instruction)
"""
